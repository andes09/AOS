# Omada — Active Work

---

## 🚀 ACTIVE — Planner Revamp (team lanes, time blocking, design system)

Rebuild the planner from a bare Mon–Fri checkbox grid into a dense, color-coded
scheduling surface: team-member lanes down the left, time-labelled task blocks
laid out chronologically. Stays org/team-scoped — lanes are people, not life
areas. Task color derives strictly from the assignee; unassigned work is grey.
Full plan: `~/.claude/plans/iridescent-soaring-hippo.md`.

**Phase 1 — Design system (frontend only, unblocked)**
- [x] `tokens.css`: define missing `--color-border-strong`; add spacing scale, z-index scale, and the 10-hue lane palette (light + dark)
- [x] `lib/laneColors.ts` — `laneVars()` as the single color decision point
- [x] `lib/date.ts` — move date helpers out of `PlannerCalendarPage`, add wall-clock time helpers
- [x] `styles/planner.css` — pseudo-selectors/keyframes only (imported from `index.css`)
- [x] `ui/`: `Avatar`, `IconButton`, `SegmentedControl`, `Tooltip` + barrel exports; `Modal` adopts `--z-modal`
- [x] Add Vitest (scoped to `src/`, so it doesn't swallow the Playwright suite) + 54 tests for the pure modules

**Phase 2 — Backend** (code complete; migration NOT yet run against a real DB)
- [x] Migration `0031_planner_attribution`: `tasks.assignee_id` (FK developers, ON DELETE SET NULL), `tasks.scheduled_time` (naive TIME), `tasks.duration_minutes`; `developers.color_index` (server_default), `developers.avatar_url`; backfill distinct color_index per team
- [x] `models/task.py` + `models/developer.py` matching columns
- [x] `_owned_developer()` helper — org-scope assignee validation (cross-tenant guard, tested)
- [x] `GET /api/roadmap/members` (single query, correlated count — no N+1)
- [x] Extend `PATCH /tasks/{id}` with assignee/time/duration via the `model_fields_set` idiom
- [x] `POST /api/roadmap/tasks` (lane "+" button) and `POST /api/roadmap/tasks/reschedule` (bulk; all-or-nothing)
- [x] `_task_json` gains the three new fields
- [x] **Ran `alembic upgrade head` against local Postgres (2026-07-19).** Verified: all 5 columns present; `scheduled_time` is `time without time zone` (naive, as intended); FK delete rule is `SET NULL`; both indexes created; color backfill correct; `alembic_version` holds exactly one row (`0031`)
- [ ] Optional: `alembic downgrade -1` then up again to prove reversibility. The downgrade compiles to correct SQL offline but has not been executed — deliberately not run against the active dev DB unprompted, since it drops columns

**Phase 3 — Sidebar + attribution**
- [x] `PlannerSidebar`, `MemberLane` (unassigned lane is the same component with `colorIndex: null`), assignee chips in the detail modal; `laneVars()` drives every card color; assignee filtering via lane click

**Phase 4 — Time model**
- [x] `PlannerPage` replaces `PlannerCalendarPage` (route updated, old file deleted); `usePlannerData`, `usePlannerMutations`, `plannerCache`, `plannerFilters`, `taskLayout`
- [x] `TimeAxis`/`HourGrid`, `DayColumn`, `PlannerToolbar`, duration presets in the modal
- [x] **Overlap decided: side-by-side column split**, not "+2 more" (see review)

**Phase 5 — Drag and drop (@dnd-kit)**
- [x] Draggable tasks; `slot:` (15-min), `day:` (all-day strip), `lane:`, `unscheduled` droppables; `PointerSensor` distance:5; `DragOverlay` at `--z-drag-overlay`

**Phase 6 — Views + detail modal**
- [x] `SegmentedControl` view switcher, day/week via shared `CalendarGrid`, `ListView`, `BoardView`, `UnscheduledTray`, `TaskDetailModal`, search filter
- [ ] Bulk "assign selected → person" (needs multi-select; `rescheduleTasks` mutation is already wired for it)

**Phase 7 — Polish**
- [ ] Wire `useProjectChat` to a chat panel; keyboard nav; Playwright specs (assign → reload → color persists; drag → reload → time persists)

### Review — Phase 1 (2026-07-19)

**Shipped.** 54 Vitest tests green, `tsc --noEmit` clean, prod build succeeds.
Phase 1 is behaviour-neutral by design — no component renders differently yet.

Two things found along the way that were *not* in the plan:

1. **`--color-border-strong` was referenced but never defined** (`PlannerCalendarPage.tsx:290`), so the task checkbox border had been silently falling through its `var()` fallback. Now defined in both themes.
2. **`apps/web`'s typecheck was already broken on main — 85 errors**, all "cannot be used as a JSX component" on lucide-react/react-router. Root `package.json` pins `@types/react` to v18 under a `pnpm.overrides` key that **pnpm 11 no longer reads** (it warns on every install), so `@types/react@19` leaked in from LandingPage (which legitimately runs React 19). Since `build` is `tsc && vite build`, the web build was failing on main. Fixed by mirroring the overrides into `pnpm-workspace.yaml` (pnpm 11's new home). Verified both `apps/web` and `LandingPage` typecheck at 0 errors afterwards. **The duplicate block in root `package.json` was left in place deliberately** — `engines` still allows pnpm ≥9, which reads the old location and ignores the new one. Keep the two in sync until the repo drops pnpm <11.

### Review — Phases 2–6 (2026-07-19)

**Shipped.** Backend: 15 new tests green (`tests/test_roadmap_planner.py`), full suite 344 passed / 24 failed — the same 24 that fail on a clean tree (verified by stashing). Frontend: 82 Vitest tests green, `tsc --noEmit` clean, prod build succeeds.

**Phase 2 caveat:** the migration is written and compiles to correct SQL offline (`alembic upgrade 0030:0031 --sql` — note it emits `TIME WITHOUT TIME ZONE`, i.e. naive, as intended), but has **not been run against a real database**. The endpoint tests all pass against in-memory SQLite via the existing `tmp_db` fixture, so behaviour is proven; only the DDL round-trip and the color backfill are unverified.

**Overlap handling — decided.** Two tasks at the same hour render **side by side at half width**, via a greedy interval-graph column pack in `taskLayout.ts`. Chose this over "+2 more" because a scheduling conflict is precisely what the user needs to see, and hiding it behind a disclosure defeats the purpose of a time grid. Clusters are computed per connected run of overlaps, so a 3-way pileup at 09:00 doesn't shrink an unrelated 14:00 task. 13 tests cover the geometry.

**Deviations from plan:**
- `WeekView` + `DayView` collapsed into one `CalendarGrid` — they differed only in column count, so two files would have been duplicated code. Day view passes `dayCount: 1`.
- `TimedTaskCard` merged into `TaskCard`. Positioning is supplied by the caller via `style`, so one card component serves the grid, sidebar, list, board, and tray. Avoids two components drifting apart.
- `AssigneePicker` / `DurationPicker` live inside `TaskDetailModal` as local chip components rather than separate files — they have no second call site yet.
- Single-task drags go through `updateTask`, not `rescheduleTasks`. The bulk mutation is wired and tested but waits for multi-select.

**Known gaps:** no Playwright coverage for the planner yet; bulk assign needs multi-select; `useProjectChat` is still unconsumed.

---

## 🚀 ACTIVE — Pivot: Onboarding v2 (project roadmap AI)

Pivot: Omada becomes an interactive project-roadmap AI. This work replaces the Jira onboarding entry path (old wizard kept behind flag) with: GitHub connect → name+phone → LLM idea interview. Deliverable = backend API + headless hooks layer (partner builds the real UI). Full plan: `~/.claude/plans/we-are-pivoting-abd-sorted-sparrow.md`.

- [x] 1. Migration `0027_onboarding_v2` + models: `developers.phone`, `github_connections`, `onboarding_sessions`, `onboarding_messages`
- [x] 2. Config (`github_client_id/secret/redirect_uri`, `anthropic_api_key`) + `onboarding_v2` flag (local true, prod false) + `featureFlags.ts`
- [x] 3. GitHub OAuth integration (`integrations/github/`, mirrors Jira): /connect /callback /status /disconnect /repos + tests
- [x] 4. Onboarding v2 router: GET /state (derived), POST /github/skip, PUT /profile, POST /complete + tests
- [x] 5. Idea interview: `services/idea_interview.py` (stream reply + tool-choice brief extraction, 40-msg cap, cost tracking); chat endpoints incl. SSE /chat/message + tests
- [x] 6. Headless layer `apps/web/src/features/onboarding-v2/` (types, api, hooks, barrel — no styling)
- [x] 7. Reference UI `OnboardingV2Page.tsx` + App.tsx flag-switched routing (`/onboarding/legacy` = old wizard, `/onboarding/v2` = explicit new flow)
- [x] 8. Playwright e2e (SSE mocked) + full verification (pytest, tsc, build, legacy spec green)
- [x] 9. Project purpose classification (hobby/startup/learning) — new explicit step, steers the idea interview's system prompt
- [x] 10. Partner frontend-integration doc (`docs/onboarding-v2-frontend-integration.md`)
- [ ] Ops (external): GitHub OAuth apps per env (callback `/api/integrations/github/callback`), Clerk GitHub social provider, `GITHUB_*` + `ANTHROPIC_API_KEY` in Railway

### Review (2026-07-13)

**Shipped.** 45 backend tests (36 original + 9 for purpose) + 3 Playwright tests, all green; `tsc` and prod build clean. Full pytest suite has 24 failures that are byte-identical on a clean tree (pre-existing: they need a local Postgres). Migrations not yet applied to a real DB — run `alembic upgrade head` when one is up (offline SQL compile verified for both 0027 and 0028).

Flow is now: `github_connect → profile → purpose → idea_chat → done`. Purpose (hobby/startup/learning) is collected as an explicit 3-way choice — not chat-extracted — because it deterministically selects one of three system-prompt variants in `services/idea_interview.py` (`_PURPOSE_GUIDANCE`), each prioritizing different things: hobby → fun/free-time/small scope; startup → market/MVP/timeline pressure; learning → skill goals/depth vs breadth. The opening chat message is also purpose-flavored. `chat/start` and `chat/message` now 409 with `purpose_not_set` if called before `PUT /purpose`.

Notes for the partner (UI): see `docs/onboarding-v2-frontend-integration.md` — full hook usage, flow diagram, local setup, and rules of the road. Short version: build against `apps/web/src/features/onboarding-v2/index.ts`, never call `fetch` directly, render off `state.currentStep` rather than hardcoding step order.

Deviations from plan: added `brief_complete` column to `onboarding_sessions` (LLM "enough" judgment is distinct from user override); added explicit `/onboarding/v2` route; made Playwright port overridable via `E2E_PORT` (local 5174 is taken by the LandingPage dev server); fixed a strict-mode-ambiguous locator in the legacy onboarding spec; added the purpose step (not in the original plan — requested afterward, ships as migration 0028).

---

## 📋 Up next active work

### Sprint Brain Quality — Phase 1 (Readiness Warnings) + Phase 2 (Auto-trim)

**Goal:** stop generating dishonest sprint plans. Fix inputs before we call the model (Phase 1) and recover after the call when the plan is still shaky (Phase 2). User edits that lower confidence are out of scope — only initial generation is gated.

**Design principle:** warnings-first, no hard blocks. One `ReadinessCard` component above the Generate button surfaces every issue; Generate is always enabled. Only truly terminal cases (zero developers, zero backlog tickets) return an inline error on click. Warnings are logged onto the trace so we can measure which ones predict bad outcomes.

---

**Phase 1a — Readiness checks (backend)**

- [ ] New service `services/sprint_brain_readiness.py` — pure function `check_readiness(team_id, candidate_tickets, developer_profiles, sprint_length_days) -> ReadinessReport`
- [ ] `ReadinessReport` shape: `{ overall_severity: "ok" | "warning" | "critical", issues: [{ code, severity, message, fix_hint, fix_url? }] }`
- [ ] Implement these checks:
  - `NO_DEVELOPERS` (critical, terminal) — zero eligible developers
  - `NO_BACKLOG` (critical, terminal) — zero candidate tickets
  - `ALL_DEVELOPERS_ON_PTO` (critical, terminal) — 0 total available days
  - `THIN_VELOCITY_HISTORY` (warning) — any developer with < 3 recorded sprints; list which ones
  - `NO_SKILL_VECTORS` (warning) — `skill_based_assignment` enabled but >50% of candidate tickets have no skill vector entries ≥ 0.2
  - `UNESTIMATED_TICKETS` (warning) — >20% of candidates have no story points
  - `BACKLOG_OVER_CAPACITY` (warning) — candidate total points > 1.5× team safe capacity; include suggested trim size
  - `NEW_TEAM` (info) — team has < 2 completed sprints on record
- [ ] Restore `_MIN_SPRINTS = 3` in `sprint_brain.py:278` — Phase 1 covers the cold-start UX gap that originally blocked this

**Phase 1b — Wire readiness into the plan endpoint**

- [ ] New endpoint `GET /api/teams/{team_id}/sprint-brain/readiness` — returns `ReadinessReport` without generating a plan; used by frontend to render the card pre-click
- [ ] In `POST /plan` — call `check_readiness` first; if `overall_severity == "critical"` and any terminal issue is present, return 400 with the report (don't call the model)
- [ ] On successful generation, attach `readiness_report` to the response so warnings echo on the returned plan
- [ ] Persist readiness report onto the generation trace (extend existing trace payload or add a column — check current shape first)

**Phase 1c — Frontend `ReadinessCard`**

- [ ] New component `apps/web/src/components/SprintPlanner/ReadinessCard.tsx`
- [ ] Renders above the Generate button on `SprintPlannerPage.tsx`
- [ ] One row per issue: severity chip (info/warning/critical), message, optional "Fix" link
- [ ] Uses TanStack Query on the readiness endpoint, refetches when team/backlog changes
- [ ] For `BACKLOG_OVER_CAPACITY` — inline "Cap candidate set at top ~X points?" toggle (defaults on) that gets passed into the generate mutation
- [ ] On the generated plan panel, show a compact banner echoing any warnings that were present at generate time

**Phase 2a — Auto-trim via `what_if_dropped` (backend)**

- [ ] Threshold constant `_CONFIDENCE_TARGET = 0.7` (top of `sprint_brain.py`, easy to tune)
- [ ] After first plan generation, if `confidence_score < _CONFIDENCE_TARGET`:
  - Pick ticket with highest value in `what_if_dropped` (biggest confidence lift on drop)
  - Remove from candidate set, re-run `create_sprint_plan` with trimmed set
  - Repeat up to `_MAX_AUTO_TRIM = 3` iterations
  - Track dropped tickets in a `deferred` list
- [ ] If still below threshold after max trims → skip to Phase 2b retry
- [ ] Return payload extended: `{ plan, deferred: [{ticket_id, reason: "auto-trimmed to raise confidence from X to Y"}], auto_trim_iterations: N }`

**Phase 2b — One tightened-prompt retry**

- [ ] If Phase 2a hits max iterations and still below `_CONFIDENCE_TARGET`, one final retry with an appended user message: "The previous pass returned confidence {X}. Identify which assignments are driving that down and either reassign to a better-fit developer or move them to deferred."
- [ ] Return whichever of (original, best-trimmed, retry) has highest confidence; label the response with which path was used
- [ ] Never return worse than the original plan

**Phase 2c — Frontend deferred surface**

- [ ] On plan render, if `deferred` non-empty, show a "Set aside to raise confidence" section below the plan
- [ ] Each deferred ticket has a "Bring back" button that re-runs generation with it forced in (bypasses auto-trim for that ticket)
- [ ] Copy: "We set these aside because including them dropped confidence below 70%. Bring them back if you want to override."

**Phase 3 — Telemetry (do alongside, not after)**

- [ ] Log every readiness report + eventual `confidence_score` + override count on the trace
- [ ] Log auto-trim iteration count and which tickets were dropped
- [ ] After ~50 traces, review: which warnings correlate with low final confidence / high override rate? Prune warnings that are noise; strengthen copy on ones that predict badly.

**Verification**

- [ ] Backend unit tests for each readiness check (fixture inputs → expected report)
- [ ] Backend integration test: team with thin history → readiness returns `THIN_VELOCITY_HISTORY`, `/plan` still succeeds and echoes the warning
- [ ] Backend integration test: backlog 3× capacity → auto-trim triggers, deferred list non-empty, final confidence above threshold
- [ ] Backend integration test: pathological inputs (all critical warnings) → returns 400 with report, no Claude call made (assert cost tracker unchanged)
- [ ] Frontend Playwright: seed a thin-history team → open Sprint Planner → verify readiness card renders warnings → generate → verify plan banner echoes warnings
- [ ] Manual: run against a real beta team, compare `confidence_score` distribution before/after over ~10 sprints

**Out of scope (intentionally)**

- Blocking user edits that lower confidence — the user retains full control post-generation
- Push-to-Jira gating — separate P0 item, tracked below
- Confidence calibration (Phase 3 of the parent Sprint Brain Quality plan) — comes after we have telemetry from Phase 1+2

---

## ✅ Done (archived)

- **Beta Onboarding Hardening (6 streams + boards-fallback footgun)** — shipped 2026-06-17 (commit `e2e4440`). Stream E (sync.py warn-on-date-parse + router.py 502 on Jira auth error), Stream B (SyncStatus model + migration 0026 + /sync-status endpoint + Sentry), Stream D (POST /onboarding/reset + tests), Stream A (test_onboarding_flow_e2e.py — 6 tests + reset tests), Stream C (frontend polling + reset button + Sentry React + Playwright smoke), Stream F (CI workflow). Boards-fallback footgun resolved by `0a98162` (drop project-* synthetic IDs, pick-project-then-board flow) plus OAuth scope fixes (`e713a1e`, `62d6ef9`, `b17a573`).
- **Onboarding Design Rebuild + Boards Fix** — full rewrite of `OnboardingPage.tsx` to match design (WelcomeStep, ConnectFlow, ConfirmTeam, Review, Done); real Jira boards via `/integrations/jira/boards` (B1); team-members endpoint (B2); confirm-team endpoint (B3).
- **Stage 2 Simulator (M1–M6)** — multi-team matrix, all archetypes, parallel execution, HTML report. 89 tests passing. Simulator retired and removed from main (2026-07-17); final state preserved at tag `archive/omada-simulator-final`.
- **Stage 2 Bug fixes (2026-05-20)** — omada_team_id clobber (A), push 409s (B), missing audit logs (C), backlog sync gap (D), Celery worker (E). Large/omada flipped 33% → 50% after Fix A.
- **Initiative A — Identifier Associations** — merged. Team glossary, skill-intensity vectors, Sprint Brain routing, Scope Cop 5th criterion, override capture + recalibration loop, sprint-close refresh hooks.
- **Initiative B — Inline Ticket Refinement** — merged (waves 0–4). Scope Cop suggested revisions, Jira write integration, conflict detection, Plan Review Modal, Sign-off Carousel, batched commit, telemetry.
- **Initiative C Phase 1 — Sprint Gen Speed** — prompt caching (cache_control on system+tools), complexity cache table (alembic 0023), SSE streaming on `/plan` with stage events; frontend stage chip. Shipped 2026-06-02.

---

## 🔧 Billing (branch: `feat/stripe-billing`) — configure before launch

All code is written and committed. Nothing to build yet — just configuration tasks when ready to go live.

### Configure Stripe
- [ ] Form LLC + open Mercury business account (do before first charge)
- [ ] Create Stripe account under business entity
- [ ] Create 3 products + recurring prices in Stripe dashboard:
  - Starter — $159/mo + $129/mo annual
  - Team — $269/mo + $219/mo annual
  - Growth — $429/mo + $349/mo annual
- [ ] Add env vars to Railway (production):
  ```
  STRIPE_SECRET_KEY=sk_live_...
  STRIPE_WEBHOOK_SECRET=whsec_...
  STRIPE_PRICE_STARTER=price_...
  STRIPE_PRICE_TEAM=price_...
  STRIPE_PRICE_GROWTH=price_...
  ```
- [ ] Register webhook endpoint in Stripe dashboard → `https://<api-domain>/api/billing/webhook`
  - Events to enable: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`

### Merge + deploy
- [ ] Merge `feat/stripe-billing` into main
- [ ] Run migration `0016_billing` on production DB
- [ ] Flip `billing: true` in `apps/api/config/features/production.yaml`
- [ ] Smoke test: hit `GET /api/billing/status` → `{status: "free", tier: null}`
- [ ] Smoke test: create a checkout session → confirm redirect to Stripe works
- [ ] Smoke test: use Stripe CLI (`stripe listen --forward-to .../api/billing/webhook`) to fire test event → confirm org subscription updates

---

## 📋 Up next

Nothing active — both major initiatives are shipped. Next work items are billing (configure + launch) and whatever comes after.

### Infra — split Celery workers by queue

- [ ] Idea: run multiple Celery worker processes, each bound to a dedicated queue, instead of one worker draining everything
  - Likely split: `jira-sync` (long, IO-heavy) | `default` (fast user-facing tasks) | `beat` (scheduled)
  - Why: a slow Jira backfill currently blocks every other task behind it; isolating queues stops head-of-line blocking and lets us tune `--concurrency` per workload
  - Cheap to do on current runtime (no k8s needed) — just additional worker processes with `-Q <queue>` and route tasks via `task_routes`
  - Revisit Kubernetes only when we outgrow PaaS-managed workers (many services, custom autoscaling, platform team) — not yet

### Sprint gen — gate commit/push on low confidence

- [ ] Idea: today `/plan` always returns a plan and the UI surfaces `confidence_score` only as a gauge (`SprintPlannerPage.tsx:472`). One-click `pushMutation` (`SprintPlannerPage.tsx:330`) fires regardless. Low-confidence plans get pushed to Jira without friction.
- [ ] Don't block generation — the lead still needs the assignments + what-if affordances to fix a shaky sprint. Generation should always run.
- [ ] Add a threshold (start ~0.5, configurable) → when `confidence_score` is below it:
  - Show a "Low confidence — review before committing" banner above the plan
  - Disable Push-to-Jira until the lead explicitly acknowledges (checkbox or two-step confirm)
  - Leave drop / what-if / refine flows fully enabled so the lead can raise confidence first
- [ ] Decide where the threshold lives — feature flag vs. team setting. Start as a constant, promote to flag if leads ask to tune it.
- [ ] Telemetry: log acknowledge-and-push-anyway events so we can see how often the gate actually catches a bad plan vs. just annoys people.

### Post-beta — Multi-board / switch-board support

Removed from beta Settings on 2026-06-07 in favour of "one board, set during onboarding." Bring back for main release.

- [ ] Decide model: one team = one board (with a "switch" replace flow) vs. one team = many boards (with per-board scoping in queries)
- [ ] Settings: add board chip + "Switch board" action (re-opens the board picker, then triggers a full re-import or board-scoped swap depending on the model above)
- [ ] If multi-board: add board selector to DashboardLayout header next to the sync control; scope every Jira-backed query by `board_id`
- [ ] Migration impact: `sprints`, `tickets`, `team_members` may need `board_id` if going multi-board
- [ ] Handle orphaned data when a board is removed (archive vs. cascade-delete — probably archive for retro/velocity continuity)

---

## ⏸️ Initiative C — Sprint Gen Speed (Phases 2–4 deferred)

Phase 1 shipped — see archived. Phases 2–4 paused pending GDPR/CCPA research.

### Phase 2 — Consent UI

**2a. Backend consent model** (alembic 0024)
- [ ] Add to `teams`: `data_training_consent BOOLEAN NOT NULL DEFAULT TRUE`, `consent_granted_at TIMESTAMPTZ`, `consent_revoked_at TIMESTAMPTZ NULL`
- [ ] Default consent_granted_at to NOW() for new teams (since opt-out default = consent implicit on team creation)
- [ ] Existing teams: backfill `consent_granted_at = created_at` in migration (treats existing users as having consented when they signed up — acceptable for opt-out model, document the choice)
- [ ] New endpoint `PATCH /api/teams/{id}/consent` — body `{consent: bool}` — sets/clears the timestamps appropriately

**2b. Onboarding checkbox** (ReviewStep)
- [ ] Add a new `<section>` between Privacy note and Footer nav
- [ ] Checkbox (defaults checked), short copy: "Help improve Omada by sharing anonymous sprint-planning patterns. We never store ticket text, names, or descriptions — only structural data like story points and skill match scores. Change anytime in Settings."
- [ ] Pipe `consent` value through `onDone` → team-setup save payload → backend writes to teams table

**2c. Settings toggle**
- [ ] Add "Data & Privacy" section to SettingsPage with the same toggle
- [ ] On toggle: PATCH endpoint, success toast, "We'll stop collecting new training data" / "Thanks — your data helps us improve"
- [ ] Show last-changed timestamp underneath

### Phase 3 — Training data capture

**3a. Training table** (alembic 0025)
- [ ] New table `sprint_generation_traces`:
  - `id UUID PK, team_id UUID FK, sprint_id UUID FK NULL, generated_at TIMESTAMPTZ`
  - `model TEXT, prompt_version TEXT` — so we can filter by model when training
  - `input_features JSONB` — see schema below
  - `output_features JSONB` — see schema below
  - `cost_usd NUMERIC, latency_ms INT, cache_hit_pct REAL` — performance telemetry
- [ ] Indexes: `team_id`, `generated_at`, `model`

**3b. Input features schema** (structured only)
```json
{
  "team": {
    "size": 6,
    "sprint_length_days": 14,
    "developers": [
      {"dev_hash": "sha256(team_id+dev_id)", "velocity_avg": 8.2, "sprints_recorded": 6,
       "skill_vector": {"sql": 0.9, "java": 0.3}, "capacity_pts": 13}
    ]
  },
  "candidates": [
    {"ticket_hash": "sha256(team_id+ticket_id)", "story_points": 5,
     "complexity_score": 0.7, "skill_vector": {"sql": 0.8}, "matched_identifier_count": 3}
  ],
  "context": {"recent_override_count": 2, "active_retro_pattern_count": 1}
}
```
- Note: dev_hash and ticket_hash are team-scoped so re-identification requires team-level access. Skill labels are stored as-is (e.g., "sql", "auth") — they may contain product-specific terms but no PII.

**3c. Output features schema**
```json
{
  "assignments": [
    {"ticket_hash": "...", "dev_hash": "...", "confidence": 0.85,
     "skill_match_score": 0.88}
  ],
  "confidence_score": 0.82,
  "warnings_count": 1,
  "what_if_dropped": {"ticket_hash": 0.87}
}
```
- ❌ Excluded: `reasoning` text, `skill_match_reasoning` text, `summary` text, ticket titles, dev names. Reasoning text can leak ticket context ("matches the Acme refactor") so it's filtered before insert.

**3d. Write path** — `services/training_trace.py`
- [ ] New `record_generation_trace(...)` called from `create_sprint_plan` after assignments computed
- [ ] **Gated by `team.data_training_consent`** — if false, no insert
- [ ] Scrubber utility `_to_training_features(input, output)` strips text fields and hashes IDs
- [ ] Wrapped in try/except so failure never breaks user flow

**3e. Override events as preference labels**
- [ ] Link existing `SprintPlanOverride` to traces via new column `generation_trace_id UUID NULL FK`
- [ ] Set during `create_sprint_plan` response: include `trace_id` in payload; frontend echoes it when override is recorded
- [ ] Result: every override row pairs with the trace that produced the original assignment → DPO-style pair ready

**3f. Sprint outcomes capture**
- [ ] In sprint-close hook (find it — `sprint_close` or similar), for each trace where `sprint_id` is set:
  - Compute: tickets_completed_count, tickets_spilled_count, points_completed, points_spilled, override_count
  - Write to new table `sprint_outcomes (trace_id PK FK, ...metrics)` or extend traces row
- [ ] Result: structured label for "did this plan actually work out"

### Phase 4 — Privacy + ops hygiene

- [ ] Document the data model in `docs/PRIVACY.md`: what we store, what we don't, retention policy
- [ ] Add retention job (cron or Celery beat): delete traces older than 18 months (configurable)
- [ ] Add admin endpoint `DELETE /api/teams/{id}/training-data` for GDPR-style requests
- [ ] Update marketing site privacy policy copy (track as separate task — not code)

### Verification (Phase 1)
- [ ] Time a full generation before/after — log latency delta to demonstrate
- [ ] Verify `cache_read_tokens` shows up in cost_tracker logs on warm runs
- [ ] Manually clear `ticket_complexity_cache` rows for one team → confirm fallback to Claude call works
- [ ] SSE: open dev console, confirm event stream emits stage events; verify JSON fallback still works for tests
- [ ] Existing test suite passes; add focused tests for cache hit path + cache miss path

### Out of scope (intentionally)
- Actually building/training the NN — separate initiative once data accumulates
- Per-stage timing on the existing cost_tracker logs (nice-to-have, defer)
- Parallelizing Scope Cop's Jira fetches (separate quick win)
- Decomposing the assignment monolith (architectural — separate plan)

