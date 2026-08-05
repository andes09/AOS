# Roadmap Drift Detection — closing the loop back to GitHub

## Implementation Notes (built 2026-08-05)

Phases 0–3 are built on `worktree-roadmap-drift-detection`, off `origin/main` (72d2dc6).
The plan below is kept as written; this records what actually shipped and where it diverged.

**Built as specified:** migration `0051` (match provenance + backfill), the pure heuristic
matcher (`services/github_matching.py`), its wiring into both ingestion paths, the Groq
classifier (`services/github_classifier.py`) chained off `reconcile_org_github`, the drift
service and `GET /roadmap/drift`, the `DriftBanner`, and `POST /roadmap/reconcile` routed
through the adjuster.

**Divergences and decisions made during the build:**

- **`match_method` is a plain `String(20)` with a `MatchMethod` constant namespace, not an
  Enum column.** This repo has been bitten three times by `SAEnum(..., native_enum=False)`
  reloading as the enum *member* and breaking `==` against string literals (recorded in
  `docs/plans/2026-07-20-plan-reconciliation.md`). A closed set of four short strings does
  not need the footgun.
- **The drift evidence is passed to the adjuster as a new `extra_context` argument, not
  written into `Task.feedback`.** The plan said "synthetic per-task feedback", but
  `Task.feedback` is the user's own writing — a derived signal overwriting it would destroy
  real input and then feed the destruction back into every subsequent adjust.
- **A third guard was added to the heuristic matcher: candidate scoping by repo.** When a
  project has `github_repo_full_name` matching the event's repo, only that project's tasks
  are candidates. Without it, an org with several projects could attach a commit in one repo
  to another project's plan.
- **`silent_repo` is guarded on the connection being older than the window.** Not in the
  original plan; without it, a repo linked yesterday reads as "no activity for 14 days" the
  day after onboarding.
- **`hasDrift` is driven by warning-severity signals only.** `ahead_of_plan` is informational
  and deliberately does not raise the banner.
- **Fixed in passing:** `roadmap_generator.py` was recording three Groq generations as
  `provider="anthropic"`, pricing them at Anthropic rates in `ai_usage_events`. All three now
  pass `provider="groq"`, matching the other four call sites.
- **`tests/test_features.py` was rewritten around invariants** rather than exact-dict equality
  on the `experimental` block. That assertion had already drifted (`tech_stack_step`) and was
  failing on `main` before this branch; it now asserts what actually matters — nothing
  experimental enabled in production, and the same key set across all three environment files.

**Not built:** Phase 4 (push channel) remains a design note, as planned.

**Verification run:** 441 API tests pass (up from 398), with 15 pre-existing failures reduced
to 7 — all 7 pre-date this branch on `origin/main`. Five are the documented "env-dependent
tests hidden by .env" trap (the adjuster tests don't patch `settings.groq_api_key`, so they
pass in a checkout with a `.env` and fail in a clean one); the other two are stale
(`_BRIEF_TOOL["name"]` against a changed tool schema, and a MagicMock leaking into a Pydantic
response model in the legacy Jira sprints router). Migration `0051` was verified
upgrade → downgrade → re-upgrade against a throwaway Postgres database, including both
backfill branches. `pnpm build` (tsc + vite) and `pnpm test` are clean.

**Still required before this does anything in production:** the Phase 0 infra steps below —
`GITHUB_APP_WEBHOOK_SECRET` and the GitHub App's webhook URL. Until those are set, no events
are ingested and every signal reads as "no drift".

## Context

Omada's roadmap is generated once and then sits static until a human remembers to hit
regenerate. Linear/Notion have the same limitation (manual updates only), and Claude's plan
mode categorically can't do better (no persistence, no connection to real work). The
differentiator is a roadmap that **watches the repo and tells the founder when the plan and
reality have diverged**.

**Most of the ingestion half already exists and is not being used.** Built and merged
2026-07-28 (`docs/plans/2026-07-20-github-task-autocomplete.md`), gated behind
`experimental.github_autocomplete`, which is `false` in both `local.yaml` and
`production.yaml`:

- App-level webhook receiver — `apps/api/src/routers/github_webhooks.py` (HMAC verify →
  resolve installation → `process_github_event.delay()`), `integrations/github/webhook_verify.py`
- Append-only event log — `models/github_activity_event.py`, unique on
  `(organization_id, repo_full_name, event_type, external_id)` = the idempotency mechanism
- Matcher + auto-complete — `integrations/github/events.py` (push → `IN_PROGRESS`,
  merged PR → `DONE`)
- 6-hourly reconciliation sweep — `github_reconciliation_sweep` in `worker.py:102-113`

So this is **not** a build-from-scratch. The missing pieces are (a) turning ingestion on,
(b) making matching good enough that the data means something, and (c) the drift layer
itself. Decisions taken: **flag drift, never auto-rewrite the plan** — a human triggers any
reflow; and matching is **heuristics first, LLM only for the residue**.

The load-bearing problem: today a commit only links to a task when the developer types
`AOS-142` into the branch/commit/PR. A solo founder driving Claude Code will essentially
never do that, so every event lands `matched_task_id = NULL` and any drift metric built on
it reads as "100% unplanned" for everyone. **Matching quality is the prerequisite, not a
follow-up** — hence the build order below.

---

## Phase 0 — Turn ingestion on (infra + two code gaps)

Nothing downstream has data until this is live.

**Manual steps (yours):**
1. Generate a secret: `python -c "import secrets; print(secrets.token_hex(32))"`.
2. GitHub App settings → Webhook URL `https://<api-host>/api/webhooks/github`, same secret,
   subscribe to **Push** and **Pull request** events.
3. Set `GITHUB_APP_WEBHOOK_SECRET` in `apps/api/.env` and in Railway.

**Code gaps found:**
- `GITHUB_APP_WEBHOOK_SECRET` is missing from `.env.example` (the setting exists at
  `config.py:30`, but an empty secret 401s every delivery — `github_webhooks.py:52` logs this
  case specially). Add it.
- Flip `experimental.github_autocomplete: true` in `apps/api/config/features/local.yaml`.
  Production stays `false` until Phase 2 ships. (`is_feature_enabled` resolves the dotted
  child directly, so the `experimental.enabled: false` parent doesn't block it.)

**Verify:** run the dev stack (Celery worker + beat auto-start, commit `c3ced2f`), expose the
API with a tunnel, push a commit whose message contains a real `Task.short_id`, confirm a
`github_activity_events` row lands and the task flips to `IN_PROGRESS`. Re-deliver the same
payload from GitHub's UI and confirm no second row and no double-apply.

---

## Phase 1 — Trustworthy matching

**Migration `0051_github_event_match_metadata.py`** (`down_revision='0050'` — re-check
`alembic heads` at build time). Adds to `github_activity_events`: `match_method`
(`String(20)`, nullable: `short_id` | `heuristic` | `llm` | `unmatched`), `match_confidence`
(`Float`, nullable), `classified_at` (`DateTime`, nullable). Backfill
`match_method='short_id'` for rows with a non-null `matched_task_id`, `'unmatched'` otherwise.

**New `apps/api/src/services/github_matching.py`** — pure, DB-free functions so they unit-test
like `services/roadmap_shapes.py`:
- `normalize_tokens(text)` — lowercase, strip punctuation, drop stopwords plus generic dev
  vocabulary (`fix`, `update`, `add`, `wip`, `chore`, `merge`, `refactor`) that would
  otherwise match everything.
- `score_candidates(*, message, branch, changed_paths, tasks)` — weighted token overlap
  against task titles/descriptions, plus prefix match of `changed_paths` against
  `Task.github_path` (a column that exists and is currently unused, `models/task.py:102-103`).
- Accept only when the top score clears a threshold **and** beats the runner-up by a margin —
  a coin flip between two tasks must resolve to "unmatched", not to an arbitrary pick.

**Extend `integrations/github/events.py`** — leave the exact `short_id` path first and
unchanged; on miss, run the heuristic scorer over the project's non-done tasks. Record
`match_method` on every insert.
- Changed file paths come from the `push` payload's `commits[].added/modified/removed`. The
  reconciliation sweep's `list_commits` doesn't return files, so heuristics degrade to
  text-only on that path — acceptable, note it in the docstring.

**New `apps/api/src/services/github_classifier.py`** — Celery task
`classify_unmatched_events(project_id)`. Batches recent `match_method='unmatched'` events with
the project's task list and asks Groq to map each to a task or to "unplanned", with a
confidence. Reuse the established shape: `AsyncOpenAI(base_url=settings.groq_base_url)`,
forced `tool_choice`, retry-on-`tool_use_failed` — copy `roadmap_generator._call_planner`
(`services/roadmap_generator.py:222`). API key via `idea_interview.resolve_api_key`. Chain it
off `reconcile_org_github` so there's one cadence rather than a second beat entry.

**Safety rule, non-negotiable:** heuristic and LLM matches are **evidence only**. Only an
exact `short_id` on a merged PR may mutate `Task.status` / `completed_at`. A fuzzy guess must
never silently tick off a founder's task.

**Small in-scope fix:** `roadmap_generator.py:479` and `:552` pass `provider="anthropic"` to
`record_generation_cost` while `_MODEL` is the Groq model — Groq usage is being priced at
Anthropic rates in `ai_usage_events`. Fix while adding the classifier's own cost recording.

---

## Phase 2 — Drift detection and the roadmap-visible flag

**New `apps/api/src/services/roadmap_drift.py`.** One query, then pure computation over a
window (default 14 days). Each signal is
`{kind, severity, headline, detail, milestoneIds[], evidence[]}`:

1. **`stalled_milestone`** — milestone has ≥1 non-done task with `scheduled_date < today`, and
   zero matched events against any of its tasks in the window.
2. **`unplanned_work`** — share of window events with `match_method='unmatched'`, plus up to 5
   representative branch names / PR titles so the founder sees *what* was built off-plan.
3. **`silent_repo`** — project has `github_repo_full_name`, connection is active, ≥1 open
   task, zero events in the window.
4. **`ahead_of_plan`** — tasks completed ≥3 days before `scheduled_date`; the plan is too
   conservative and later milestones should pull in.

`Milestone` has **no status and no dates** (`models/milestone.py` is title + description +
`sort_order`) — all milestone timing is derived from its tasks' `scheduled_date`. A milestone
whose tasks are all unscheduled must read as *not drifting*, not as permanently stalled.

**Endpoint** `GET /api/projects/{project_id}/roadmap/drift` in `routers/roadmap.py` — the
router is already project-scoped with `mark_developer_active` and has `_owned_project`.
Returns `{hasDrift, computedAt, windowDays, signals[]}`. Computed on read, no snapshot table
(same posture as `activity.re_engagement_summary`). New flag `experimental.roadmap_drift`,
added to **all three** YAMLs (`local`/`production`/`test` — past flag drift is recorded in
`tasks/todo.md:461`).

**Frontend:**
- `apps/web/src/pages/planner/useDriftSignal.ts` — `useQuery`, key `['drift', projectId]`.
- `apps/web/src/components/planner/DriftBanner.tsx` — self-gating (returns `null` when
  `!hasDrift`), modeled directly on `components/activity/WelcomeBackBanner.tsx`, rendered with
  `components/ui/Alert.tsx` variant `warning`. Dismiss in `sessionStorage` keyed by project —
  no persistence, no migration.
- Mount at the top of `PlannerPage.tsx`'s ready state; mark drifting milestones in
  `components/planner/MilestoneMap.tsx` using `milestoneIds`.
- Flag read through the existing `apps/web/src/featureFlags.ts`.

---

## Phase 3 — Human-triggered reflow

`POST /api/projects/{project_id}/roadmap/reconcile`. Turns the drift signals into synthetic
per-task feedback ("4 commits on `feat/auth-refactor` map to nothing in the plan"; "3 overdue
tasks, no activity in 21 days") and calls the **existing `services/roadmap_adjuster.py`**.

Deliberately the adjuster, **not** `regenerate_milestone` — the latter does
`DELETE FROM tasks WHERE milestone_id = ...` wholesale (`roadmap_generator.py:528`), wiping
statuses, assignees and `completed_at`. The adjuster already treats `done`/`in_progress` as
fixed history, already reads `Task.feedback`, and already creates new milestones when needed.
That makes the reconcile endpoint thin and the reflow non-destructive by construction. The
adjuster's `_SYSTEM_PROMPT` gains a GitHub-evidence section.

Triggered only by a button on the drift banner. Never automatic.

---

## Phase 4 — Push channel (design note, not built)

The drift signal composes with `docs/plans/2026-07-20-anti-dormancy-mvp.md` — Milestone 1
(`services/activity.py`) shipped, Milestones 2–3 (dormancy job, email) did not. When they do,
a drift signal is another reason to nudge. Keep `roadmap_drift.compute_drift()` free of side
effects so that path is additive.

---

## Non-goals

Auto-reflow without a human; storing commit diffs or patch content; GitHub Actions/CI events;
Issues sync; multiple repos per project; persisted drift history or snapshots.

## Known traps

- `Task.status` is `SAEnum(..., native_enum=False)` — a reloaded row carries the enum
  *member*, so `==` against a string silently misbehaves. Use the `_status_str` helper pattern
  (`integrations/github/events.py:60`).
- `Task.depends_on` needs explicit `selectinload` at every call site
  (`models/task.py:118-131`).
- Branch fresh off `main` — the current checkout is `fix/onboarding-idea-chat-stuck-handshake`.
- Copy this plan to `docs/plans/2026-08-05-roadmap-drift-detection.md` at build time, per repo
  convention.

## Verification

1. **Phase 0:** real webhook delivery from a tunnel lands a row and flips a `short_id`-tagged
   task; GitHub's "Redeliver" produces no duplicate.
2. **Phase 1:** `apps/api/tests/test_github_matching.py` — pure scorer tests including the
   ambiguity case (two similar tasks ⇒ unmatched). Extend
   `apps/api/tests/test_github_webhooks.py` with a heuristic-match case, asserting the task
   status does **not** change on a fuzzy match. `alembic upgrade head` then `downgrade -1`
   clean.
3. **Phase 2:** `apps/api/tests/test_roadmap_drift.py` against the sqlite `tmp_db` fixture —
   seed each of the four signals plus the all-unscheduled milestone case (must not drift) and
   a healthy project (`hasDrift` false). Then run the app end-to-end: seed an overdue
   milestone, load `/app/projects/:id`, confirm the banner renders and the milestone is marked
   in `MilestoneMap`; confirm it vanishes with the flag off.
4. **Phase 3:** run reconcile on a project with a done task and an in-progress task; confirm
   both survive with `completed_at` intact and only `todo` tasks were replanned — diff the
   task table before/after.
5. Full suites: `uv run pytest` in `apps/api`, `pnpm test` in `apps/web`.
