# Anti-Dormancy MVP for Omada

## Context

Omada's core risk isn't a broken feature — it's the user going quiet. Someone signs up, does the AI "idea interview," generates a roadmap, and then life happens: they get busy, get bored, or open the full task tree and feel overwhelmed by how much is left. Right now there is **nothing in the product that notices this or does anything about it**: no activity tracking on users, no email sending, no in-app "here's where you left off" moment. The roadmap either gets finished or quietly dies, and the team has no signal either way.

This plan is a **lean MVP**, chosen deliberately over a full engagement system: prove the loop (detect dormancy → nudge → user returns) with the cheapest possible version of each piece before investing in streaks, richer digests, or Slack DMs. Channels prioritized, in order: (1) activity tracking + in-app re-engagement — ships with zero new external dependencies, (2) a scheduled dormancy-detection job, (3) a single narrow email nudge — the first new external dependency in the plan. A fourth channel, GitHub-driven passive progress, is a separate in-flight feature (`docs/plans/2026-07-20-github-task-autocomplete.md`); this plan just makes sure its output composes cleanly with dormancy tracking once it ships.

## Codebase grounding

- **Product loop**: Clerk auth → Organization → onboarding chat builds a brief → "Generate roadmap" creates `Project → Milestone → Task` rows → user works the roadmap/planner. One project per org today.
- **`apps/api/src/models/developer.py`**: `Developer` is keyed by `team_id`, not directly by org (`Organization → Team → Developer`). It's shared with the legacy Jira-roster feature — **`clerk_user_id` and `email` are both nullable**, because some `Developer` rows are just roster placeholders imported from Jira, not real signed-in accounts. No `last_active_at` exists today. This matters: any activity write or email send must filter to `clerk_user_id IS NOT NULL` (and `email IS NOT NULL` for sends), or we'll track/email phantom rows.
- **`apps/api/src/auth.py`**: `get_current_user_id` returns the Clerk `sub` claim (matches `Developer.clerk_user_id`); `get_current_org_id` returns the Clerk org id.
- **`apps/api/src/routers/roadmap.py`**: the whole roadmap surface — `GET /api/roadmap`, `PATCH /api/roadmap/tasks/{task_id}` (status/assignee changes), etc. Router currently has no dependencies attached; it's the single highest-signal hook point since it's the landing surface + every task mutation.
- **`apps/api/src/models/task.py`**: `Task.status` is a 3-state enum (`todo`/`in_progress`/`done`), `assignee_id` nullable (`SET NULL` on developer delete), `updated_at` exists but there's no `completed_at`.
- **`apps/api/src/worker.py`**: Celery + Redis already running scheduled jobs via `celery_app.conf.beat_schedule` (two entries today: daily + 15-min Jira sync). Adding a new dormancy job is a dict entry + one new task module, following the exact pattern in `apps/api/src/integrations/jira/sync.py`.
- **No email infra**: confirmed no SendGrid/Resend/Postmark/SMTP dependency anywhere in `apps/api/pyproject.toml` or `apps/web/package.json`. `apps/api/src/services/slack.py` is the closest existing pattern for "send an external notification" (plain `httpx` POST, never raises, returns bool) — the email service should mirror this shape. `httpx` is already a dependency, so an HTTP-API email provider (Resend) needs no new SDK.
- **No in-app notification system**: `apps/web/src/layouts/DashboardLayout.tsx` has just a theme toggle. `apps/web/src/pages/roadmap/RoadmapPage.tsx` is the actual `/app` landing page and sources everything through the `features/roadmap` barrel (`apps/web/src/features/roadmap/index.ts`) — new frontend work must follow that convention, not fetch directly.
- **Master-dashboard plan** (`docs/plans/2026-07-20-master-dashboard.md`, in-flight/uncommitted) adds event-log tables (`ai_usage_events`, `github_commit_daily`) for admin charting. Deliberately **not** reusing that pattern here — dormancy only ever needs "when did this person last do something," which a single mutable `last_active_at` timestamp answers with an O(1) write, no aggregation. Building an event log now would be scope creep for a feature explicitly asked to stay lean.
- **Migration numbering caveat**: `apps/api/alembic/versions/` currently ends at `0031_planner_attribution.py`. The master-dashboard plan is also uncommitted and may claim the next revision number first — at build time, run `ls apps/api/alembic/versions/ | sort | tail -5` and chain `down_revision` to whatever is actually head; don't hardcode against numbers in this doc.

## Design decision: why one timestamp, not an event log

Two different consumers need "is this user dormant," and they need it at two different times:
- The in-app banner is **pull-based** — computed live on the one request that matters (loading the roadmap). No Celery job needed for this path at all.
- The email nudge is inherently **push-based** — it has to run on a schedule, whether or not the user is around to trigger it.

A single `Developer.last_active_at` column serves both. It's also the seam that makes the plan compose with the still-unbuilt GitHub task-autocomplete feature for free: when that feature flips a task to `done` from a webhook, it just needs to call the same "touch activity" function against the task's assignee — the dormancy job doesn't need to know GitHub exists.

## Milestone 1 — Activity tracking + in-app re-engagement

No new external dependencies, no Celery involvement.

**Backend**
- Migration: add `developers.last_active_at` (nullable `DateTime`).
- New `apps/api/src/services/activity.py`: `touch_developer_activity(developer_id, db)` and `touch_by_clerk_user(clerk_user_id, db) -> previous_last_active_at`. Kept as a standalone module (not inlined in a router) so the future GitHub task-autocomplete Celery path can import and call it too.
- `apps/api/src/dependencies.py`: add a `mark_developer_active` dependency wrapping `touch_by_clerk_user`, filtering to developers with a non-null `clerk_user_id`.
- `apps/api/src/routers/roadmap.py`:
  - Attach `mark_developer_active` as a router-level dependency (covers roadmap load + every task mutation with one line).
  - In the `PATCH /tasks/{task_id}` handler, when `status` transitions to `done`, also call `touch_developer_activity` for `task.assignee_id` if set (so a teammate's task completion resets *their* clock, not just the clicker's) — for now, if unassigned, skip rather than fan out to the whole org, to keep this milestone simple.
  - New `GET /api/roadmap/summary` endpoint, using `mark_developer_active` as an explicit per-route `Depends()` (not just the router-level one) so the handler can read the *previous* `last_active_at` before it's overwritten. Returns: `is_returning`, `days_since_last_active`, `tasks_remaining`, `tasks_completed_since_last_visit`, `overdue_count`, and `next_up` (top 3 todo tasks) — this list is the direct answer to "overwhelmed," giving a capped next-step view instead of the full tree.

**Frontend** (follow the existing `features/roadmap` barrel convention)
- `apps/web/src/features/roadmap/types.ts` — add `RoadmapSummary` type.
- `apps/web/src/features/roadmap/api.ts` — add `getSummary()`.
- `apps/web/src/features/roadmap/hooks/useRoadmapSummary.ts` (new) — TanStack Query wrapper.
- `apps/web/src/features/roadmap/index.ts` — export both.
- `apps/web/src/components/roadmap/WelcomeBackBanner.tsx` (new) — renders nothing if `is_returning` is false; otherwise shows days-away + what changed + the `next_up` list + overdue count. Match `RoadmapPage.tsx`'s current unstyled Phase-A convention.
- Mount at the top of `RoadmapPage.tsx`'s ready-state render, above the project tree.

**Verification**: seed a developer with `last_active_at` several days in the past, load `/app/roadmap`, confirm the banner renders with correct counts/next-up and disappears on the next load (timestamp refreshed). Confirm a recently-active developer sees no banner. Flip a task to `done` for a different assignee and confirm their `last_active_at` updates independent of who clicked it.

## Milestone 2 — Dormancy detection job

Adds a Celery beat entry; no schema changes, no user-facing effect yet — this milestone is provable in isolation before any side effect exists.

- New `apps/api/src/services/dormancy.py`, mirroring the shape of `apps/api/src/integrations/jira/sync.py`. `detect_dormant_developers()` finds developers where: org has completed onboarding, has a project with at least one incomplete task, developer has a non-null `clerk_user_id`, and `COALESCE(last_active_at, onboarding_completed_at) < now() - interval`. Buckets: **soft** (3–6 days, logged only — the in-app banner already covers this live), **deep** (7+ days — the trigger for Milestone 3's email).
- Register in `apps/api/src/worker.py`'s `beat_schedule` (e.g. daily, offset from the existing Jira sync times) and add the module to `celery_app`'s `include` list.

**Verification**: seed a developer 10+ days dormant on an org with an incomplete roadmap, run the task synchronously in a shell, confirm correct bucketing; seed a second developer whose roadmap is fully done and confirm they're excluded; confirm the beat entry shows up in `celery -A src.worker beat` startup logs.

## Milestone 3 — Email digest MVP

First new external dependency: **Resend**. Chosen because it's a plain HTTPS POST (`httpx` is already a dependency — no new SDK), mirrors the existing `slack.py` notification pattern, and its free tier comfortably covers MVP volume. Postmark is an equally-valid same-effort alternative if there's an existing account preference.

- Migration: `developers.email_notifications_enabled` (bool, default true), `developers.unsubscribe_token` (nullable string); new `dormancy_notifications` table (`developer_id`, `channel`, `bucket_days`, `dedupe_key` = ISO week, `resend_message_id`, `created_at`, unique on `(developer_id, channel, dedupe_key)` — the unique constraint *is* the dedupe mechanism, one email per person per dormant week).
- `apps/api/src/config.py`: add `resend_api_key`, `email_from_address` (start on Resend's sandbox domain until a real sending domain is verified — a real prerequisite, not a code task).
- New `apps/api/src/services/email.py`, same contract shape as `slack.py` (never raises, returns success + message id). One narrow email: "pick up where you left off" — remaining task count, the single next task title, a link back to the roadmap, plain-text unsubscribe footer. Not a digest — that's explicitly deferred.
- New `apps/api/src/routers/notifications.py`: unauthenticated `GET /api/notifications/unsubscribe/{token}` that flips `email_notifications_enabled` off. Token generated lazily via `secrets.token_urlsafe(32)` (same call `invitation.py` already uses) on first send.
- Extend `detect_dormant_developers` (or a sibling task on the same beat entry): for each deep-bucket developer with notifications enabled, a real email, and no `dormancy_notifications` row for the current ISO week, send + record. Gate the actual send behind a feature flag (`config/features/{env}.yaml`: `dormancy_email_digest`, default off) so the job can run and be observed via logs before real email goes out.

**Verification**: seed a deeply-dormant developer with a real test email and the flag on locally, run the job, confirm exactly one email arrives via Resend; re-run in the same week and confirm no second send (constraint holds); hit the unsubscribe link and confirm a subsequent run skips them.

## GitHub composability (design note only — not building GitHub auto-complete here)

Keep `touch_developer_activity()` a standalone, side-effect-pure function. When the separate GitHub task-autocomplete feature lands and flips a task to `done` from a webhook, it just needs to call this same function against the task's assignee. Because the dormancy job reads one `COALESCE(last_active_at, ...)` column fed by every activity source, it benefits automatically — no dormancy-job changes required when that feature ships. No action needed now beyond not breaking this seam.

## Explicit non-goals for this MVP

Streaks/momentum framing, a full multi-task weekly digest, per-developer Slack DMs (distinct from the existing team-level `SprintAlert` webhook system), nuanced dormancy scoring (weighted recency, per-user thresholds, send-time optimization), an event-log-based activity table, and delivery-status tracking (opens/clicks via Resend webhooks — `resend_message_id` is stored now specifically so this is an additive follow-up, not a rework).

## Critical files

- `apps/api/src/models/developer.py` — add `last_active_at`, `email_notifications_enabled`, `unsubscribe_token`
- `apps/api/src/services/activity.py` (new)
- `apps/api/src/services/dormancy.py` (new)
- `apps/api/src/services/email.py` (new)
- `apps/api/src/routers/roadmap.py` — router dependency, task-completion hook, new `/summary` endpoint
- `apps/api/src/routers/notifications.py` (new) — unsubscribe endpoint
- `apps/api/src/worker.py` — beat schedule entry
- `apps/api/src/config.py` — Resend settings
- `apps/web/src/features/roadmap/{types.ts,api.ts,index.ts,hooks/useRoadmapSummary.ts}`
- `apps/web/src/components/roadmap/WelcomeBackBanner.tsx` (new)
- `apps/web/src/pages/roadmap/RoadmapPage.tsx`

## Sequencing

1. **Milestone 1** (activity tracking + in-app banner) — ship first, zero new infra, immediately useful even if nothing else follows.
2. **Milestone 2** (dormancy detection job) — observable via logs before anything sends.
3. **Milestone 3** (email nudge) — first external dependency, gated behind a feature flag until verified end-to-end.
4. **Later, dependent on the separate GitHub auto-complete project** — confirm it calls `touch_developer_activity()` per the composability note; no new work required in this plan.
