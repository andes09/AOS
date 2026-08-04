# Omada — Active Work

_Last reconciled against `main` on 2026-08-04 (HEAD `6e42fb6`)._

---

## 🚧 IN FLIGHT — unmerged branches

- `fix/planner-rate-limit-stops-generation` — Groq 429s now stop plan
  generation instead of cascading into more calls. See the section below.

Both previously-stranded branches were merged to `main` on 2026-08-04
(see "Stranded branch cleanup" below). Everything else in this file is on `main`.

---

## 🚧 Groq rate limits stop plan generation (2026-08-04)

`RuntimeError: Groq API rate limit reached` was indistinguishable from every
other upstream failure, so each layer treated it as retryable.

- [x] `services/llm_errors.py` — `LLMRateLimitError` (a `RuntimeError`
      subclass, so existing `except RuntimeError -> 502` arms still work) plus
      `is_rate_limit()`, which catches a rate limit delivered *mid-stream* as
      a bare `APIError` (the SDK only maps HTTP responses to
      `RateLimitError`).
- [x] Raise it from all three Groq services (generator, adjuster, interview),
      with one shared message.
- [x] `_call_planner_stream` checks `is_rate_limit` *before* the
      tool_use_failed retry, so a 429 never spends another attempt.
- [x] `prewarm_roadmap` (Celery) gives up instead of `self.retry(countdown=15)`
      — 15s later it's the same quota window, and the prefetch is optional.
- [x] `POST /plan/draft` emits `error: rate_limited` (its own code, not
      `roadmap_generation_failed`); PlanReviewStep says so and offers
      "Try again" next to "Continue anyway".
- [x] REST/MCP surfaces map it to **429** (was 502): roadmap
      generate/regenerate/adjust/milestone-regenerate, projects
      sessions/{id}/generate, artifact import analyze, MCP `rate_limited:`.

### Review

Verified by tests, not inspection: no-retry on both call paths (`await_count
== 1`), mid-stream 429 recognised, nothing persisted on failure, prewarm skips
retry while other failures still retry, `/plan/draft` emits `rate_limited`,
and the REST path returns 429. Full API suite: 378 passed, 3 pre-existing
failures (`test_features`, `test_project_brief`, `test_sprints_router` — all
fail identically on a stashed tree). `tsc --noEmit` clean.

---

## ✅ SHIPPED — Stranded branch cleanup (merged to main 2026-08-04)

Two finished branches had been pushed to `origin` and then never merged.

- [x] `feature/task-dependency-graph` → merge commit `365cb52`. Note the
      namesake work (`3523ed1` + migration `0046_task_dependency_graph`) was
      *already* on `main`; the branch had been reused for one unrelated
      follow-up, `1430e60` (roadmap plan sizing). That single commit was all
      that was outstanding. Merged clean, no conflicts.
- [x] `feat/onboarding-completion-confirmation` → rebased onto `main`
      (`66dab39` → `be708f9`), merge commit `6e42fb6`.

### Review (2026-08-04)

**Why they were stranded.** `feature/task-dependency-graph` had no blocker at
all — it auto-merged with zero conflicts; the merge step was simply never run
after the last commit. `feat/onboarding-completion-confirmation` had a real
one, and a silent one: it carried `0035_onboarding_awaiting_confirmation.py`
declaring `revision = '0035'` / `down_revision = '0034'`, but `main` already
had `0035_task_parallel.py` with **the identical pair**, with `0036` chained
off it. Different filenames, so git reports no conflict and merges happily —
the break only surfaces at `alembic upgrade head` on a duplicate revision id.

**Fix.** Rebased onto `main`, then `git mv` to
`0048_onboarding_awaiting_confirmation.py` with `revision = '0048'` /
`down_revision = '0047'`. `alembic heads` → single head `0048`;
`alembic history` confirms a linear `0047 -> 0048` tail.

**Verification.** `test_roadmap_generator.py` 27 passed; `test_idea_interview.py`
20 passed (includes the three new confirmation-turn tests); together on merged
`main`, 47 passed. `npx tsc --noEmit` in `apps/web` exits 0. Also confirmed the
`_SYSTEM_PROMPT` f-string conversion in `roadmap_generator.py` is safe post-merge
— constants are imported at line 42–44, well above the line-70 use, and an AST
walk shows exactly three interpolations and no stray braces.

**Follow-up fixed (1/2) — undeclared test dep.** `aiosqlite` is required by
`conftest.py`'s `sqlite+aiosqlite:///:memory:` engine but was absent from
`apps/api/pyproject.toml` and `uv.lock`, surviving in the main venv only as a
manual `uv pip install`. Every fresh worktree failed 13 tests until someone
installed it by hand. Now declared in the `dev` extra and locked.

**Follow-up fixed (2/2) — env-dependent test.**
`test_chat_stream_error_event_on_failure` was the only test in
`test_idea_interview.py` not patching `src.services.idea_interview.settings`,
so `resolve_api_key` 402'd before the request ever reached the mocked
`run_interview_turn`. It passed locally purely because the gitignored
`apps/api/.env` supplies a real `GROQ_API_KEY` — it would fail on any clean
checkout or in CI. Now patches `settings` like its siblings.

Both caught by building a throwaway worktree off `main` and running with
`uv sync --extra dev` alone: 47 passed with no `.env` and no manual installs.
Full backend suite on `main`: **344 passed / 3 failed**, and those same 3
(`test_features::test_local_yaml_loads`,
`test_project_brief::test_brief_tool_derivation_matches_original_hand_written_shape`,
`test_sprints_router::test_current_sprint_returns_active_sprint`) fail
identically at `c12f836`, i.e. pre-existing and untouched by this work.

**Branch cleanup (done).** Both branches are gone — local refs, remote refs, and
their worktrees (`.claude/worktrees/task-dependency-graph`,
`../AOS-onboarding-confirmation`). Deleted rather than force-pushed, since the
work is on `main` and the rebase had made the remote refs unfixable without
`--force-with-lease`.

Verified contained before deleting, not assumed. `git cherry` flagged
`origin/feat/onboarding-completion-confirmation` as carrying 1 unmerged patch —
that was the pre-rebase `66dab39`, whose patch-id differs only because of the
migration renumber. Comparing the two commits' content lines with the
`revision`/`down_revision`/`Revision ID`/`Revises` lines excluded: **392 lines,
identical**. Nothing lost. Both worktrees were clean (no modified or untracked
files) at removal.

The repo's 9 stashes were left untouched — they are repo-global and shared with
other concurrent sessions.

**Still open (unrelated housekeeping):** `git fetch` warns about a stale
`.git/gc.log` and a backlog of unreachable loose objects, so automatic gc is
disabled. Deliberately not run — `git prune` would discard exactly the kind of
unreachable commit (e.g. the pre-rebase `66dab39`) that is worth keeping
recoverable for now, and other sessions share this repo.

---

## ✅ SHIPPED — Plans always start with environment setup (merged to main 2026-08-04)

Roadmap generation only told the planner to front-load "install tools/create
accounts" tasks when the founder answered the tech-stack onboarding step with
"I'm new to this". Everyone else (experienced founders, or flag-off sessions)
got plans that assume the dev machine is already configured for this specific
project. Full plan: `~/.claude/plans/fancy-mixing-reef.md`.

- [x] Add always-on `_ENV_SETUP_GUIDANCE` constant in `roadmap_generator.py`,
      appended unconditionally in `_brief_prompt` (full-roadmap gen only, not
      single-milestone regen)
- [x] Sharpen `_tech_stack_prompt`'s `"experienced"` branch: familiarity with a
      tool isn't the same as having it installed for this project
- [x] Update/add tests in `test_roadmap_generator.py` for the new unconditional
      behavior
- [x] Run `pytest tests/test_roadmap_generator.py -q`

### Review (2026-08-04)

**Shipped.** Pure prompt-text change, no schema/frontend/flag touched.
`test_roadmap_generator.py`: 17 passed (was 15; added
`test_brief_prompt_always_includes_environment_setup_guidance`, extended two
existing tests). Full backend suite: 285 passed / 43 failed — confirmed via
stash-and-rerun that the same 43 fail on a clean `origin/main` checkout in this
fresh worktree (pre-existing baseline, unrelated to this change; auth/env-config
shaped, not something this task should touch).

**Environment note (ironic given the task):** this worktree needed `uv sync
--extra dev` (pytest wasn't in the base `uv sync`) and a local-only `uv pip
install aiosqlite` (missing from `pyproject.toml`/`uv.lock` entirely — the main
checkout's `.venv` has it, but nothing declares it) before tests would even
collect. Did not add `aiosqlite` to `pyproject.toml` — out of scope for this
task and worth its own fix separately.

### Follow-up (2026-08-04): stream plan-draft roadmap generation

The plan-review step's roadmap draft was one blocking, non-streamed Groq call,
so the progress bar (`PlanReviewStep.tsx`'s `useStagedProgress`, added
separately on `main`) was a fake timer crawling toward an asymptote — user
asked how to actually speed up/improve the perceived latency of that step.

- [x] `roadmap_generator.py`: new `_call_planner_stream` (streams the forced
      tool call, accumulates `delta.tool_calls[].function.arguments`
      fragments, reports 0-95% progress via `on_progress`); `generate_roadmap`/
      `generate_roadmap_once` take an optional `on_progress` callback
- [x] Live spike against real Groq confirmed `stream=True` + forced
      `tool_choice` works (6/7 runs; the 1 failure was the pre-existing
      `tool_use_failed` flakiness, surfacing as a bare `APIError` mid-stream
      rather than `BadRequestError` — retry logic adjusted accordingly)
- [x] `onboarding_v2.py`: `/plan/draft` returns plain JSON for the idempotent
      case, SSE (`progress`/`done`/`error`) only when actually generating
- [x] Frontend: `api.ts`'s `draftPlan` consumes the SSE stream (content-type
      branch for the idempotent JSON fast path); `PlanReviewStep.tsx`'s
      `useLiveProgress` replaces `useStagedProgress`, driven by real progress,
      monotonic against mid-stream retries
- [x] Tests: new streaming-fake helpers (`_call_planner`/`_call_planner_stream`
      both served by one stream-aware `_fake_groq`) across
      `test_roadmap_generator.py`/`test_onboarding_v2.py`/`test_projects.py`

### Review (2026-08-04)

**Shipped, merged with `origin/main`'s Anti-Dormancy work below** (both
touched `roadmap_generator.py`/`onboarding_v2.py`/`PlanReviewStep.tsx` at
overlapping but non-overlapping-in-intent spots — reconciled by hand, notably
threading `on_progress` through `main`'s `generate_roadmap_once` prewarm-race
wrapper, which didn't exist when this was first built). 122 backend tests
green across the 3 touched files; `tsc --noEmit` clean. Manual browser
click-through still outstanding — no `.env`/DB/auth configured in this
worktree to run the full stack.

---

## ✅ SHIPPED — Anti-Dormancy MVP, Milestone 1 (merged to main 2026-08-03, `0bdea3d`)

Spec: `docs/plans/2026-07-20-anti-dormancy-mvp.md` (Milestone 1 only, per user).
Plan reconciled against current code (roadmap router is project-scoped; slack.py
deleted; Task.completed_at already exists; frontend has no features/roadmap —
landing is ProjectHubPage). Summary is **org-scoped**, banner lands on ProjectHub.

- [x] Migration for `developers.last_active_at` (nullable DateTime) — landed as
      `0047_developer_last_active_at` after renumbering around the concurrently
      built `0046_task_dependency_graph` (single head confirmed via `alembic heads`)
- [x] `services/activity.py` (new): `touch_developer_activity()`, `touch_by_clerk_user()`, `re_engagement_summary()`
- [x] `dependencies.py`: `mark_developer_active` (filters clerk_user_id IS NOT NULL; commits the touch itself so a GET's activity signal doesn't ride on an implicit end-of-request commit)
- [x] `routers/roadmap.py`: attach `mark_developer_active` router-level; PATCH→done touches assignee's clock
- [x] `routers/roadmap.py`: PATCH→done sets `completed_at`, reopen clears it (latent manual-flip gap — summary's "completed since last visit" needs it)
- [x] `routers/activity.py` (new): `GET /api/activity/summary`, registered in main.py
- [x] Frontend: `features/activity/{types,index,hooks/useActivitySummary}` + `components/activity/WelcomeBackBanner.tsx` (self-hides unless returning; dismissable), mounted atop ProjectHubPage
- [x] Verify: `tests/test_activity.py` — 6 tests pass (returning counts+next_up, touch overwrites so 2nd call not returning, recently-active & first-visit not returning, completed_at stamp + assignee touch, reopen clears). No regressions (8 failures are pre-existing, confirmed via stash). tsc + vite build clean.

### Review — Milestone 1 complete (2026-08-03)
- **Reconciliation deltas from the 2026-07-20 doc**: summary is org-scoped (not `/api/roadmap/summary`) since roadmap is now project-scoped w/ multiple projects per org → new `GET /api/activity/summary`; banner lands on `ProjectHubPage` (the real `/app` landing), not a `RoadmapPage`; `slack.py` gone so the never-raises pattern is plain `httpx`-style but M1 needs no external call; `Task.completed_at` already existed but the **manual PATCH path never stamped it** — fixed here because the summary depends on it.
- **One remaining manual step**: `alembic upgrade head` against the real DB (adds `developers.last_active_at`). Not run unprompted — it's a schema change on the live dev DB, same posture as the 0031 note above.
- **Deferred (per user)**: Milestone 2 (dormancy Celery job) and Milestone 3 (Resend email). The `touch_developer_activity()` seam is standalone so both compose without changes.

---

## ✅ SHIPPED — everything else merged to main, 2026-07-28 → 2026-08-04

Reconstructed from the commit log; these landed while `todo.md` was tracking the
two features above and were never written down here.

### Observability — comprehensive error logging (branch `chore/comprehensive-error-logging`, worktree `../AOS-logging`, merged `adeea4f`)

The whole app was flying blind: nothing configured the root logger, so every
`logger.info()` was dropped and warnings/errors fell through to
`logging.lastResort` (bare message to stderr, no timestamp/level/traceback).
The web app had **zero** `console.*` calls and no error boundary anywhere.

- [x] `cd60154` **Backend foundation** — `src/logging_config.py` (one stdout
      handler on root; JSON in production, human-readable elsewhere;
      request/user/org `ContextVar`s stamped onto every record; noisy
      third-party loggers turned down). `src/request_logging.py` (per-request
      correlation id honouring inbound `X-Request-ID` and echoing it on the
      response; access logging with status/duration/client IP; slow requests at
      WARNING). `main.py`: `setup_logging()` before anything else can log,
      handlers for `RequestValidationError`/`HTTPException` (which previously
      left no server-side trace), startup DB connectivity probe in a lifespan
      handler. `worker.py`: Celery `task_failure`/`task_retry`/`prerun` signals
      so roadmap prewarm and the GitHub sweep can't fail silently. `auth.py`
      now distinguishes "Clerk unreachable" from "bad token".
      **`/health` deliberately still does no DB I/O** — it's Railway's
      healthcheck, and a round-trip there turns pool exhaustion into container
      restarts.
- [x] `4726592` **Frontend** — `lib/logger.ts` (console + Sentry; real `Error`s
      keep their stack via `captureException`; global
      `unhandledrejection`/`error` handlers), `components/ErrorBoundary.tsx`
      (mounted at root and around `<App/>`; logs component stack, shows a
      recoverable panel instead of a white screen), `lib/api.ts` logs
      network-level failures / non-JSON 2xx bodies / non-OK responses (5xx
      error, 4xx warn) and `ApiError` now carries the server's `X-Request-ID`
      so a front-end report joins to the backend trace, `main.tsx`
      QueryCache/MutationCache `onError`.
- [x] `d7c4502` **MCP + remaining silent swallows** — a `_logged` wrapper on all
      9 MCP tools (MCP calls bypass the HTTP stack entirely, so neither the
      middleware nor the FastAPI exception handlers ever saw them; `ToolError`
      → WARNING, anything else → ERROR with traceback; all 9 schemas preserved
      through `functools.wraps`). Plus `invitations.py`, `organizations.py`,
      `database.py` rollback tracing.
- [x] `3c21599` **Redaction + cause reporting** — the 422 handler was logging
      Pydantic's raw `errors()`, whose `input` field carries the offending
      value; verified a failing `POST /api/settings/anthropic-key` **would have
      written a customer's API key into the logs**. Now only `loc`/`type`/`msg`.
      Also: webhook secret-missing (ERROR) vs signature mismatch (WARNING),
      named `ENCRYPTION_KEY` failure causes, `LOG_LEVEL`/`LOG_FORMAT`/`SENTRY_DSN`
      documented in `.env.example`.
- [x] `54435b2` **Fix double-printed SQL** — once a root handler existed,
      `echo=True` printed every statement twice (SQLAlchemy's own
      `StreamHandler` plus propagation to ours). Propagation off for
      `sqlalchemy.engine.Engine` when echo is on; noise floor lifted entirely at
      `LOG_LEVEL=DEBUG`.

### Onboarding v2 flow

- [x] `65b2edc` (2026-07-30) **Tech-stack step** — required, flag-gated
      (`experimental.tech_stack_step`) step between purpose and build_plan,
      asking founders what they already know (or that they're new to building
      software). Feeds the roadmap prompt directly: known tools preferred,
      "new to this" gets explicit beginner setup tasks in milestone 1. Also
      fixed a pre-existing test bug (`test_local_yaml_loads` asserted
      week/day/board view were true when `local.yaml` has them false).
- [x] `b79e5ec` (2026-08-03) Enable that step in `local.yaml` — it was fully
      built but the flag was left off when experimental flags were zeroed out,
      so it never appeared outside test runs.
- [x] `3cc5da6` (2026-08-04) Add a **Cloud & Hosting** category to the
      tech-stack step — founders often know a deploy target (Railway, Azure,
      AWS) even when unsure about frameworks.
- [x] `a7e9aa7` (2026-08-03) **Review-before-commit plan step + path-aware
      repo** (flags `plan_review`, `repo_create`). Roadmap generation moved out
      of the silent `POST /complete` into an idempotent `POST /plan/draft`;
      `POST /plan/confirm` records acceptance (`onboarding_sessions.
      plan_confirmed_at`, migration `0044`). New derived `plan_review` step with
      Regenerate / Looks good, never-bricks (draft failure offers "continue
      anyway"). Persist `github_connections.account_type` (migration `0045`);
      `GithubClient.create_repo`; `POST /repo/create` rejects non-org installs
      with 422, since **personal-account installation tokens can't create
      repos**.
- [x] `64df285` (2026-08-03) Update GitHub connect copy — `Administration:write`
      means the old "read-only / never writes to your repos" line was
      inaccurate; reframed as creates-only-when-asked, never modifies existing
      code, revocable.
- [x] `e00c269` / `114237c` (2026-08-04) **Consolidate GitHub connect + repo
      select into one step** — merged `github_connect` and `repo_select` into a
      single skippable `github_repo` step (two phases behind a new
      `GithubRepoStep` wrapper), moved to **position 5** (after `build_plan`)
      instead of being the very first thing a user sees, so `onboardingPath` is
      already known when the path-aware "create a repo" offer renders.
- [x] `c12f836` (2026-08-04) **Back button** — the backend derives `currentStep`
      from data completeness and has no "previous step" concept, so this is a
      client-side view override in `OnboardingV2Page`; re-saving an
      already-complete step doesn't change what's incomplete, so `currentStep`
      lands back where it was once the override clears.
- [x] `e5ed261` (2026-07-28) **Generate the roadmap on complete, land on the new
      plan** — the chat path marked the session completed but never created a
      Project/roadmap (unlike the import path), so users landed on `/app` with
      zero projects and got the empty "create new project" screen instead of the
      plan Omada had just drafted. `/complete` now generates best-effort (a
      failure still completes onboarding) and returns the project id; `DoneStep`
      navigates to `/app/projects/{projectId}`.
- [x] `05b0009` (2026-08-03) **Prewarm roadmap generation via Celery** — fire
      Groq generation as soon as the interview completes rather than on
      `/plan/draft`'s critical path; `generate_roadmap_once` resolves the
      prewarm-vs-draft race via the `Project.onboarding_session_id` unique
      constraint. Also dropped the dead TAWOS importer references (`pymysql`
      dep, `.gitignore` entry).

### Planner

- [x] `595111b` (2026-07-29) **Nested planner-view flags** under a `planner`
      group (`list` itself ungated; the switcher hides disabled options and
      falls back to List). Also deleted two flags gating dead surface area:
      `allow_team_creation_via_api` (two endpoints with zero callers — removed
      outright rather than leaving permanently-403 dead code) and `slack_alerts`
      (a fully-built but never-called Slack feature — settings UI, router and
      `slack_configs` table all removed, migration `0042`).
- [x] `355ec84` / `6c6d209` (2026-07-29) **Enforce sequential task ordering** —
      the "waits its turn" fade was cosmetic; non-parallel tasks could be
      completed out of order in both API and UI. `PATCH /tasks/{id}` now returns
      409 `task_blocked_by_earlier_task`; Up next checkbox disabled for waiting
      tasks; window bumped 2 → 3.
- [x] `5752d41` (2026-07-30) **Fix which view is gated** — `DayAgenda` ("Up
      next") is the permanent main page and must never be hideable, but it was
      gated behind `planner.day_view` (off locally), leaving the multi-day
      `ListView` as the hardcoded ungated fallback. Swapped: `day` is always
      available, the renamed `planner.daily_calendar_view` gates `list`. Filter/
      fallback logic extracted into a shared `usePlannerViewOptions()` (it was
      duplicated and *inconsistent* between `TopBar` and `DashboardLayout`).
- [x] `0728068` (2026-07-30) **Up next is an unlimited stream** — the daily list
      was scoped to one calendar day, so finishing a couple of tasks dead-ended
      into an unwanted "Plan more for today" AI prompt instead of continuing
      into tasks already generated for later days. Day boundary removed
      entirely; backend sequential blocking now spans the whole project,
      matching `claim_next_task`. **The extend-day AI top-up was removed
      outright (superseded, not hidden), and delete-task was removed everywhere**
      — deleting a task disturbs the sequential ordering others depend on.
- [x] `3523ed1` (2026-08-03) **Explicit dependency graph replaces the `parallel`
      flag** — a flat boolean ("doesn't block on the task before it") can only
      express strict sequencing, not real prerequisites. Adds a
      `task_dependencies` join table + `Task.depends_on` (migration `0046`); the
      generator/adjuster now emit real `key`/`dependsOn` edges, so the planner
      can unlock genuinely parallel tracks feeding a later integration task.
- [x] `5632e76` (2026-08-03) Removed the dead Anthropic API key card from
      Settings (leftover from pre-pivot Sprint Planning/Retro Prep;
      `get_anthropic_key()` has no callers), and pinned the "Plan map" button to
      the lower fifth of the viewport so its position doesn't depend on queue
      length or scroll.

### Fixes & config

- [x] `871c7bb` (2026-07-28) **All `experimental.*` flags default to false** in
      `local.yaml`, matching production. Also fixed real test-env drift:
      `conftest.py` never forced `ENVIRONMENT=test`, so local `pytest` silently
      picked up whatever a developer's `apps/api/.env` set. **This, plus
      `config/features/test.yaml` now existing, closes the old known issue about
      `ENVIRONMENT=test` blowing up on a missing flag file.**
- [x] `bf9ef3c` (2026-08-03) **Account-deletion 500** — `DELETE /api/users/me`
      threw a Postgres FK violation because `projects`, `ai_usage_events` and
      `github_activity_events` all FK to `teams.id`/`organizations.id` without
      `ondelete=CASCADE` and weren't cleaned up first; **every real account
      (which always has a project) hit this.** Added the missing deletes plus a
      regression test that reproduces the violation on the old code. Also
      stopped `SettingsPage` fetching lead-only `/api/invitations` for every
      user, which logged a 403 for anyone below lead.
- [x] `ec63f77` (2026-08-03) **Migration `0025` fix** — the remap `UPDATE` ran
      while `tickets_assignee_id_fkey` still pointed at `team_members`, so
      setting `assignee_id` to a developer id violated the constraint
      immediately. Drop the old FK before the remap, add the new one after.



## ✅ DONE — Stage 5: Omada MCP Server (branch: feature/omada-mcp-server, merged to main)

Spec: `docs/plans/2026-07-20-omada-mcp-server.md` + corrections in the task prompt
(9th `list_projects` tool, `project_id` threading, pin `mcp==1.28.1`, gate behind
`experimental.mcp_server`, extract `roadmap_service.py` from the CURRENT
project-scoped `roadmap.py`, only add `Task.completion_note` — not `completed_at`,
already exists). Do not commit; do not switch branches.

### Spike findings (mcp==1.28.1, confirmed against real installed package)
- `AccessToken` needs no subclassing at all — it already has a builtin
  `claims: dict[str, Any] | None` field, and `get_access_token()`
  (`mcp.server.auth.middleware.auth_context`) returns the exact object
  `load_access_token` constructs (confirmed via `AuthenticatedUser.__init__`,
  which stores it as-is). Used `claims` directly for
  `clerk_org_id`/`clerk_user_id`/`developer_id` — simpler than the doc's assumed
  subclass approach, no contextvars fallback needed.
- `.well-known` placement: `create_auth_routes` registers `/authorize`, `/token`,
  `/register`, `/revoke`, `/.well-known/oauth-authorization-server` as ROOT-relative
  routes on the Starlette app `FastMCP.streamable_http_app()` returns; that same app
  also serves the MCP transport at `streamable_http_path` (default `/mcp`)
  internally. **Mount the whole app at FastAPI root "/"**, not "/mcp" (mounting at
  "/mcp" would double-nest to `/mcp/mcp` and misplace `.well-known`). issuer_url =
  plain API origin (no path); resource_server_url = `{api_url}/mcp`.
- `client.client_secret` is compared via `hmac.compare_digest` against a PLAINTEXT
  value returned by `get_client()` — the SDK has no hash-and-compare path. Deviation
  from doc: store `client_secret_enc` (Fernet-encrypted via `src/services/
  encryption.py`, reversible) instead of a one-way hash. Real MCP clients register
  as public PKCE clients (`token_endpoint_auth_method="none"`, no secret at all) so
  this mostly matters for spec-correctness on the less-common path.
- PKCE/expiry/redirect_uri-match checks all happen in the SDK's own `TokenHandler`
  before our provider is called — our `exchange_authorization_code`/
  `exchange_refresh_token` just mint+persist tokens.
- `mcp==2.0.0` confirmed on PyPI (`pip index versions mcp`) — pinned to exactly
  `1.28.1` via `uv add "mcp==1.28.1"` (apps/api's actual package manager; plain
  `pip install` silently installs into system/anaconda Python since the uv venv
  ships no `pip` binary — cleaned up the accidental global install).

### Steps
- [x] Read spec + ground-truth files, spike the real SDK
- [x] `roadmap_service.py` extraction (behavior-preserving) + reran
      test_roadmap.py/test_projects.py/test_roadmap_planner.py (62 passed)
- [x] Migration 0040 (tasks.completion_note only) + 0041 (oauth tables)
- [x] Models: oauth_client.py, oauth_authorization_code.py, oauth_token.py
- [x] auth_roles.py: role_at_least(role, minimum) — also fixed to normalize
      AppRole enum members (3rd instance of the SAEnum reload footgun)
- [x] database.py: db_session() context manager
- [x] mcp_server/oauth_provider.py, mcp_server/tools.py (9 tools incl. list_projects)
- [x] routers/mcp_oauth_consent.py
- [x] main.py: mount FastMCP app at root (last, after every other route —
      first attempt placed it too early and shadowed /api/me, caught and fixed)
      + consent router, both gated
- [x] config/features/{local,production,test}.yaml: experimental.mcp_server
- [x] apps/web: McpAuthorizePage.tsx + /mcp/authorize route + featureFlags.ts
- [x] Tests: OAuth e2e (test_mcp_oauth.py, 11 tests), per-tool, flag gate,
      default-project rule — all passing
- [x] pytest tests/ -v --tb=short → 283 passed, same 8 pre-existing failures
- [x] apps/web: tsc --noEmit clean, vitest run 82 passed, prod build clean
- [x] Prepended Implementation Notes to docs/plans/2026-07-20-omada-mcp-server.md

All 5 stages of the 2026-07-20 plan-reconciliation build are now complete and
merged to main (Project Hub 0036, Import Artifacts 0037, GitHub Task
Auto-Complete 0038, Master Dashboard 0039, Omada MCP Server 0040/0041).

---

## ✅ SHIPPED (Phases 1–7, bar the gaps noted below) — Planner Revamp (team lanes, time blocking, design system)

> **Superseded in places by later work (see the Planner entries above).** Day
> scoping, the extend-day AI top-up and delete-task were all removed on
> 2026-07-30 (`0728068`); `DayAgenda` ("Up next") is now the permanent main view
> and the `parallel` boolean was replaced by a real dependency graph
> (`3523ed1`). Treat the phase notes below as history, not as current design.

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
- [x] Wire `useProjectChat` to a chat panel (the assistant FAB — see review below)
- [ ] Keyboard nav; Playwright specs (assign → reload → color persists; drag → reload → time persists)

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

### Review — Immersive shell (2026-07-21)

**Shipped.** Restructured the app into a single immersive planner surface. `tsc --noEmit` clean, 82 Vitest tests green, prod build succeeds.

- **Removed the left app-sidebar.** `DashboardLayout` is now a top bar (`components/layout/TopBar.tsx`) over a full-height content area. The top bar carries the Omada wordmark + `TeamSwitcher`, the **Week/Day/List/Board switcher promoted to primary nav**, and utilities (theme, settings gear→modal, user).
- **View state lifted to the layout** and shared with the planner via React Router `useOutletContext` (`PlannerOutletContext` in `components/planner/plannerViews.tsx`) — the top-bar tabs and the planner now read/write one `view`. The switcher was removed from `PlannerToolbar`.
- **Member-lane panel is collapsible** — a `PanelLeftClose/Open` toggle in the toolbar (and a chevron in the panel header) hides/shows it; state persists in `localStorage['aos_planner_lanes']`. When hidden, the calendar goes full-width.
- **Planner is the only `/app` route** (`<Route index element={<PlannerPage/>}>`); `roadmap`, `sprint-planner`, `settings`, `settings/calibration` routes deleted. Settings is modal-only now.
- **Deleted:** `pages/roadmap/RoadmapPage.tsx`, the orphaned `features/roadmap/` barrel (sole consumer was RoadmapPage), `pages/settings/CalibrationSuggestionsPage.tsx` + the dead "Calibration Suggestions" settings section (referenced the removed Sprint Brain), and `tests/e2e/roadmap.spec.ts` (tested the deleted page — asserted `/app/roadmap`, "No roadmap yet", "Generate roadmap"). Fixed `InviteAcceptPage`'s stale `/app/sprint-planner` → `/app`.

**Left intentionally:** `docs/roadmap-frontend-integration.md` documents the now-deleted `features/roadmap` barrel — stale, flagged but not deleted (docs, not code). `TeamSwitcher` still has off-brand hardcoded dark colors and self-hides for single-team orgs; it renders nothing today, worth a restyle when multi-team returns.

**Not a merge issue but surfaced during this work:** roadmap generation needs `ANTHROPIC_API_KEY` in `apps/api/.env` (the generator moved Groq→Anthropic in the merge). The app starts and everything but "Generate my plan" works without it.

### Review — Plan assistant FAB (2026-07-21)

**Shipped.** A clear (translucent, backdrop-blurred) circular "?" button floating bottom-right — TikTok-Tako style — that opens a Groq-backed chat for refining the plan. `tsc` clean, 82 Vitest tests green, build succeeds.

- **`components/planner/AssistantChat.tsx`** — the FAB + a floating chat card. Consumes the previously-unused **`useProjectChat`** hook (SSE streaming from `POST /api/roadmap/chat/message`, transcript from `GET /api/roadmap/chat`). Both endpoints run on **Groq** via `idea_interview.resolve_api_key` — verified they survived the merge.
- **Glassy styling** via `color-mix(... transparent)` + `backdrop-filter: blur()`, so it's theme-aware automatically; hover/focus in `.pl-fab` (styles/planner.css). Sits at `--z-dropdown` (below the settings modal).
- **"Rebuild plan with this info"** footer action → new `regenerate` mutation in `usePlannerMutations` (`POST /api/roadmap/regenerate`). Gated behind an explicit click with a visible warning that it **replaces current tasks and their assignments** (regenerate is destructive — it replans milestones/tasks, losing assignee/time customizations). Errors (e.g. missing `ANTHROPIC_API_KEY`, since regenerate uses Anthropic) surface inline in the panel.
- Rendered only in the roadmap-exists view, not the empty state (which already has its own generate flow).

**Placement note:** bottom-right corner (conventional FAB spot, satisfies "right-hand side"). Easy to move to mid-right if a more literal Tako position is wanted.

### Review — Daily agenda + Groq feedback loop (2026-07-21)

**Shipped.** Each day is now its own detailed page with per-task feedback boxes, and Groq re-plans upcoming tasks from that feedback non-destructively. Backend: migration `0033` applied to local Postgres (`tasks.feedback`, single-row `alembic_version`), 5 new tests green (20/20 in `test_roadmap_planner.py`), full suite 172 passed / 8 failed — the **same 8 pre-existing failures** (verified by stashing `apps/api/src`: identical 8, all in `test_idea_interview`/`test_project_brief`/`test_sprints_router`, none touched). Frontend: `tsc` clean, 82 Vitest green, build succeeds.

- **Timestamps now real** — the generator (`roadmap_generator.py`) gained `startTime`/`durationMinutes` in its tool schema + prompt, and sets `scheduled_time`/`duration_minutes` in `_add_tasks`. Every freshly generated/regenerated plan is timed. (Pre-existing plans stay `null` → render "Anytime" until regenerated or adjusted.)
- **New Groq adjuster** — `src/services/roadmap_adjuster.py`, `POST /api/roadmap/adjust`. Mirrors `idea_interview`'s Groq client + forced-tool pattern (not the Anthropic generator). **Non-destructive:** preserves `done`/`in_progress` tasks (status + assignee), replaces only `todo` tasks, and only within milestones the model returns. Empty/malformed model output is a no-op, never a wipe. Normalizes the `TaskStatus` SAEnum via `_status_str` (loaded rows return the enum member, not a string — that bit both JSON serialization and status comparisons; tests caught it).
- **Per-task feedback** — `tasks.feedback` column; `feedback` added to `TaskUpdateRequest` (via `model_fields_set`) and `_task_json`. Saving a note is a plain `PATCH /tasks/{id}`.
- **Frontend** — default view flipped to **day** (`DashboardLayout`); Week retained. New `components/planner/DayAgenda.tsx`: vertical chronological agenda, each task = time rail + title + full description + 3-state status + feedback textarea (saves **on blur** when changed). "Update my plan from feedback" button → new `adjust` mutation. `RoadmapTask.feedback` + `TaskPatch.feedback` added.

**Carried-forward tradeoff (unchanged):** re-planned tasks are new rows, so they come back unassigned; done/in-progress keep their assignee. Fine at current scale.

---

## 🐛 Known issues / small follow-ups

- [ ] `apps/web/tests/e2e/onboarding-v2.spec.ts` — the purpose-step test uses a
      stale locator: `getByRole('button', { name: /A startup/ })`, but
      `PurposeStep.tsx` renders the three purpose choices as `role="radio"`
      (a `radiogroup`, not buttons). Update the locator to `getByRole('radio', ...)`.
      Found 2026-07-20 while verifying the legacy-onboarding-removal branch;
      confirmed via `git diff origin/main` that neither file was touched by
      that change, so it predates it and is a pure test-locator bug.
      Still open — re-verified 2026-08-04: `PurposeStep.tsx:31` renders a
      `role="radiogroup"` of `role="radio"` options, and the spec still calls
      `getByRole('button', …)` at line 120 even after `e00c269` rewrote much of
      that file.
- [ ] Onboarding v2 — Ops (external, not code): GitHub OAuth apps per env
      (callback `/api/integrations/github/callback`), Clerk GitHub social
      provider, `GITHUB_*` + `ANTHROPIC_API_KEY`/`GROQ_API_KEY` in Railway.
      Blocks onboarding v2 going live in production (flag is currently off
      there). **Now also needs the GitHub App's `Administration:write`
      permission** for the onboarding "create a new repo" path (`a7e9aa7`) —
      and note that path only works for org installs; personal-account
      installation tokens cannot create repos.
- [ ] `apps/web/src/pages/OnboardingV2Page.tsx`'s Back button is a client-side
      view override only; the backend has no notion of a previous step. Fine
      today, but a future step whose data can't be re-saved idempotently would
      break the "override clears → lands back where it was" assumption.
- [x] ~~`apps/api/config/features/test.yaml` never existed while CI sets
      `ENVIRONMENT: test`~~ — **fixed.** `test.yaml` now exists, and `871c7bb`
      made `conftest.py` force `ENVIRONMENT=test` so local runs match CI
      deterministically instead of picking up a developer's `.env`.

---

## ✅ Done (archived)

- **B8: drop legacy Jira schema** — 2026-07-20, branch `chore/b8-drop-legacy-jira-schema` (**since merged into `main`** — confirmed 2026-08-04 via `git branch --merged main`), built on top of the now-merged `chore/legacy-teardown-b2-b7` (PR #29, B2–B7). Deferred schema-removal step: migration `0032_drop_legacy_jira_schema.py` drops tables `dependencies`, `ticket_analyses`, `jira_connections`, `sync_status` and columns `teams.jira_board_id`/`jira_project_key`/`jira_import_status`/`jira_import_sprints_imported`, `developers.jira_account_id`/`capacity_hours_per_week`; deletes the 4 corresponding model files, `tawos_importer/`, `seed_sprints.py`. **Scope was narrowed from the original ask** — investigation showed `tickets`, `sprints`, `sprint_tickets`, `developer_velocity_profiles` are still live (alerts/capacity/sprints/teams/developers/users routers) and `developers.skill_ratings`/`domain_strengths` back the live recalibration feature, so none of those were touched. Verified: local Postgres upgrade→downgrade→upgrade round-trip clean; downgrade recreates empty structures only (no data restore, documented in the migration docstring); applied cleanly against an actual production snapshot (prod was on `0026`, 93 `jira_connections` rows + other real data confirmed destroyed as intended, scratch DB discarded after); full backend suite at the pre-existing 163-passed/11-failed baseline (no regressions). **Caught and fixed one real regression along the way**: `routers/users.py`'s account-deletion cleanup had raw-SQL `DELETE FROM dependencies/ticket_analyses/jira_connections` that a class-name-only grep sweep missed — a table-name string sweep in addition to symbol grep is now the standard check for future table-drop migrations. Also found & removed 3 stale `JIRA_CLIENT_*` keys from local `.env`/`apps/api/.env` (gitignored, blocked local app boot after B7 removed those `Settings` fields — pre-existing, unrelated to this migration).

- **Pivot: Onboarding v2 (project roadmap AI)** — shipped 2026-07-13. Replaced the Jira onboarding entry with GitHub connect → profile → purpose classification (hobby/startup/learning) → LLM idea interview (`services/idea_interview.py`, SSE streaming, 40-msg cap). Headless hooks layer at `features/onboarding-v2/` + reference UI `OnboardingV2Page.tsx`. 45 backend tests + 3 Playwright green; partner integration doc at `docs/onboarding-v2-frontend-integration.md`. Outstanding: GitHub OAuth ops config, tracked above.

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

1. Merge the two in-flight branches at the top of this file (`feature/task-dependency-graph`
   is a clean single-file change; `feat/onboarding-completion-confirmation`
   needs a rebase + migration renumber off `0035`).
2. Run `alembic upgrade head` against the real dev/prod DBs — `main` is at
   `0047` and the last few migrations (`0044`–`0047`) have only been exercised
   against SQLite/local Postgres.
3. Prod ops for onboarding v2 + roadmap generation (GitHub App
   `Administration:write`, `GITHUB_*`, `GROQ_API_KEY`/`ANTHROPIC_API_KEY` in
   Railway), then flip the production flags.
4. Anti-Dormancy Milestones 2 (dormancy Celery job) and 3 (Resend email) —
   deferred, and the `touch_developer_activity()` seam composes with both.
5. Billing (configure + launch), below.
