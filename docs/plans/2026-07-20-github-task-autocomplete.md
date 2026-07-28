# GitHub-Driven Task Auto-Complete (event-driven, not pure cron)

## Implementation Notes (built 2026-07-28)

This plan was written against a per-repo-webhook / OAuth-token design that predates commit
`a4c70d0` (GitHub OAuth App → GitHub App migration). It was implemented with a corrected,
GitHub-App-native design instead. The sections below are kept as-written for history; this note
records what actually shipped and why it diverges.

**Ingestion model — one app-level webhook, not per-repo registration.** A GitHub App has a single
webhook URL, configured once in the App's own settings (an infra step — the plan's `create_webhook`
/ `delete_webhook` client methods and "register hook on connect" flow were never built). That one
URL receives `push`/`pull_request` events for every installed repo across every org automatically,
so the entire "does this token have admin rights on this repo → webhook vs. poll" question the
original plan spent most of its design on doesn't exist anymore. Consequently, dropped entirely:
- `github_repo_sync_state` table and its `sync_mode` (`'webhook'|'poll'`) split — no table, no column.
- The 15-min poll-fallback beat job — nothing to fall back *from* per-repo, since coverage is total.
- Per-connection `webhook_secret` — replaced by one app-level secret, `github_app_webhook_secret` in
  `apps/api/src/config.py` (env var `GITHUB_APP_WEBHOOK_SECRET`), following the exact pattern of the
  existing `github_app_id`/`github_app_private_key` settings. Empty locally; tests inject a real
  value via `patch`, same idiom as `tests/test_github_router.py`.

**Kept, as the plan specified:** `Task.short_id` + `Organization.next_task_seq`, `Task.completed_at`,
the `github_activity_events` table (its `UNIQUE (organization_id, repo_full_name, event_type,
external_id)` constraint is the idempotency mechanism for both the webhook and the reconciliation
sweep), the webhook receiver (signature verification, event parsing, a Celery task, and the
push→`IN_PROGRESS` / merged-PR→`DONE` matching rules), and a periodic reconciliation sweep as a
safety net for missed deliveries.

**Reconciliation cursor simplified.** Rather than a `github_repo_sync_state.last_synced_at` row, the
sweep uses `MAX(occurred_at)` per `(organization_id, repo_full_name)` straight from
`github_activity_events`, falling back to the `GithubConnection.created_at` when a repo has no
recorded events yet. One less table, since nothing else needed a persisted per-repo sync-state row
once there was no `sync_mode` to track. Runs every 6h via Celery beat
(`github-reconciliation-sweep`).

**Feature flag.** Everything above (webhook router + beat entry) is gated behind
`experimental.github_autocomplete` (nested under the existing `experimental` block in
`apps/api/config/features/{local,production,test}.yaml`), off in production, mirroring how
`routers/artifact_import.py` gates itself behind `experimental.import_artifacts` — the router 404s
while the flag is off, and the beat entry simply isn't registered.

**Migration.** Real Alembic head at the time this was built was `0037_artifact_import.py`; this
shipped as `apps/api/alembic/versions/0038_github_task_autocomplete.py` (`down_revision='0037'`) —
adds `tasks.short_id` (nullable, plain index — see below) and `tasks.completed_at`,
`organizations.next_task_seq`, and the `github_activity_events` table, with a backfill of `short_id`
for every pre-existing task in creation order per org.

**Deviations from this plan doc's specifics, found once the real code was read:**
- `Task.short_id` is **not** a globally-unique DB column, despite "unique per org" in the original
  spec reading like it might be. `Task` has no denormalized `organization_id` (it's three joins away
  via `Milestone → Project → Team`), and two different orgs' slugs can normalize to the same prefix
  after alnum-stripping — so a *global* unique constraint would be the wrong invariant and a spurious
  cross-tenant collision risk. Uniqueness *within* an org is guaranteed instead by the atomically
  incremented `Organization.next_task_seq` counter (`src/services/task_ids.py`,
  `UPDATE ... RETURNING`), and every match lookup is scoped by `organization_id` via that same join,
  so an identical short_id string existing in two unrelated orgs is harmless.
- `Task.short_id` allocation was wired into **every** task-creation call site, not just
  `routers/roadmap.py`'s quick-add endpoint: `services/roadmap_shapes.py` (AI-drafted roadmap
  persistence, shared by the chat and import-artifact paths), `services/roadmap_adjuster.py`
  (feedback re-plan + extend-day), and `services/roadmap_generator.py`'s regenerate paths. The
  quick-add endpoint creates a small minority of real tasks — most come from the AI planner — so
  only wiring the manual endpoint would have left auto-complete non-functional for most of a plan.
  `allocate_short_ids(org, count, db)` reserves a whole batch in one `UPDATE ... RETURNING` rather
  than one round trip per task.
- `GithubClient.list_pull_requests` has no server-side `since` filter to give it — GitHub's
  `/pulls` endpoint doesn't support one (unlike `/commits`, which does). It sorts by `updated`
  descending and filters client-side instead; fine for a low-frequency reconciliation sweep, not
  meant for deep historical backfill.
- No pre-existing sync-`Session`/event-loop-bridge pattern to reuse: the Jira sync module this plan
  pointed to (`src/integrations/jira/sync.py`) had already been deleted (Jira/Ticket phase-out,
  `docs/plans/2026-07-20-plan-reconciliation.md`). `process_github_event` and
  `reconcile_org_github` instead bridge via `asyncio.run()` into the existing async
  `AsyncSessionLocal` — no second, redundant sync engine.
- Idempotent inserts use `sqlalchemy.dialects.{postgresql,sqlite}.insert(...).on_conflict_do_nothing(...)`,
  picked by `db.bind.dialect.name` at call time (both dialects expose the same `ON CONFLICT` API
  shape) rather than being hard-committed to Postgres-only syntax — this repo's tests run against an
  in-memory SQLite (`tests/conftest.py`'s `tmp_db`), and there's no real Postgres available in this
  environment to test a Postgres-only upsert against.

## Context

The ask started as "plan a cron scheduler that tracks GitHub PRs/commits/code changes," but the real goal is an **auto-complete feature**: when a developer pushes commits or merges a PR referencing a roadmap task, that task should check itself off — without a human going back to mark it done. A pure polling cron was the initial instinct, but polling on a timer is wasteful in off-hours and adds latency the rest of the time (you're either burning cycles when nothing happened, or waiting up to a full interval after something did).

Exploration surfaced two things that reshape this:

1. **An uncommitted plan already exists** (`docs/plans/2026-07-20-master-dashboard.md`, section 6) speccing a *separate* daily Celery job that writes commit counts into a `github_commit_daily` aggregate table — built purely for a dashboard chart, with no per-commit/PR identity and no task-matching. Building a second, independent GitHub sync mechanism alongside it would mean two ingestion pipelines doing overlapping work. Per the decision made while planning this, **this plan supersedes that section** — one ingestion pipeline feeds both the dashboard and task auto-complete.
2. **`Task` (the roadmap entity) has no short identifier today.** `Ticket` (the legacy, pre-pivot Jira entity) has Jira-style keys (`PROJ-123`) and already auto-completes from Jira status sync — but Jira/Ticket is being phased out per recent cleanup commits. The entity that actually needs auto-complete is `Task`, and it needs a referenceable ID before commits/branches/PRs can point at it.

The design is **webhook-first, polling as a fallback only**:
- Primary path: register real GitHub repo webhooks (`push`, `pull_request`) using the existing OAuth token's `repo` scope — no GitHub App migration needed. Events land near-instantly, and nothing runs when nothing happens.
- Fallback path: some repos won't grant webhook registration (token owner isn't a repo admin → 403). Those specific repos get short-interval polling (15 min, mirroring the existing Jira incremental-sync cadence). Everything else is push-driven.
- Safety net: a low-frequency reconciliation sweep (every 6h) across *all* repos catches missed webhook deliveries (downtime, delivery failures) without being the primary mechanism.

This reuses patterns already in the codebase: Celery + Redis (`apps/api/src/worker.py`, `beat_schedule`, `Procfile` worker/beat processes) and the Jira sync shape (`apps/api/src/integrations/jira/sync.py` — sync `Session`, event-loop bridge for async GitHub calls, `pg_insert(...).on_conflict_do_update(...)` upserts, `@celery_app.task(bind=True, max_retries=3)` with rollback + `SyncStatus` on failure).

## Data model changes

1. **`Task.short_id`** (new column, e.g. `"AOS-142"`, unique per org) — the human-referenceable handle developers put in branch names / commit messages / PR titles.
   - New `Organization.next_task_seq` (int, default 0), atomically incremented (`UPDATE ... SET next_task_seq = next_task_seq + 1 RETURNING next_task_seq`) in the same transaction as task creation in `apps/api/src/routers/roadmap.py`'s task-create path, to avoid races.
   - Prefix derived from `Organization.slug` (uppercase, alnum-only, truncated) — confirm at build time whether slug is a good fit or a dedicated prefix field is needed.
   - Backfill migration assigns `short_id` to existing tasks in creation order.
   - Also add `Task.completed_at` if it doesn't already exist, mirroring `Ticket.completed_at`, so auto-complete has somewhere to record *when*.

2. **`GithubConnection.webhook_secret`** (new column) — random per-connection secret generated on connect, used for HMAC verification of inbound webhook payloads.

3. **New table `github_repo_sync_state`** (one row per org+repo): `organization_id`, `repo_full_name`, `sync_mode` (`'webhook'|'poll'`), `webhook_id` (GitHub's hook ID, nullable), `last_synced_at`/`last_synced_sha`. Populated when repos are enumerated at connect time; drives which repos the 15-min poll fallback actually touches (most repos will be `'webhook'` and the poll job skips them entirely).

4. **New table `github_activity_events`** (append-only): `id`, `organization_id`, `repo_full_name`, `event_type` (`commit`/`pr_opened`/`pr_merged`/`pr_closed`), `external_id` (commit SHA or PR number+action), `branch`, `title_or_message`, `author_login`, `url`, `matched_task_id` (nullable FK to `tasks`), `occurred_at`, `created_at`. **`UNIQUE (organization_id, repo_full_name, event_type, external_id)`** — the upsert conflict target, so webhook delivery and reconciliation/poll paths never double-write. This table replaces `github_commit_daily`: the dashboard's future `GET /api/platform-admin/commits` groups this by `date_trunc('day', occurred_at)` instead of reading a separate aggregate.

Scope note (per the dashboard plan's decision, carried forward): track all repos visible to the org's connected token — no separate allowlist.

## Backend changes

1. **Webhook registration** — on GitHub connect (and on a manual "resync repos" action), for each repo from `list_repos()`, call `POST /repos/{owner}/{repo}/hooks` (events `["push","pull_request"]`, url `{API_BASE_URL}/api/webhooks/github`, secret = connection's `webhook_secret`). Success → `github_repo_sync_state.sync_mode = 'webhook'`. 403/404 (no admin rights on that repo) → `sync_mode = 'poll'`, no hard failure.

2. **Webhook receiver** — new `apps/api/src/routers/github_webhooks.py`, `POST /api/webhooks/github`:
   - No user auth (GitHub can't present our auth) — instead verify `X-Hub-Signature-256` via HMAC-SHA256 against the connection's `webhook_secret`, using `hmac.compare_digest` (new `apps/api/src/integrations/github/webhook_verify.py`). Look up the connection via `github_repo_sync_state` by repo full name in the payload.
   - Read `X-GitHub-Event` header, do the minimal work to stay under GitHub's ~10s webhook timeout, then hand off via `process_github_event.delay(org_id, event_type, payload)` and return 200 immediately.

3. **Celery task `process_github_event`** (new `apps/api/src/integrations/github/events.py`):
   - Upserts into `github_activity_events` (idempotent on the unique constraint above).
   - Regex-extracts `short_id`-style tokens (pattern like `[A-Z]+-\d+`) from commit message, branch name, and PR title/body.
   - Matching rule: a `push` event referencing a task marks it `IN_PROGRESS` (work is happening); a `pull_request` webhook with `action == "closed"` and `merged == true` referencing a task marks it `DONE` and sets `completed_at`. PR *open* alone does not complete a task — only merge does.

4. **Celery beat entries** in `apps/api/src/worker.py`:
   - `github-reconciliation-sweep`: `crontab` every 6h — fans out `reconcile_org_github(org_id)` per active `GithubConnection`, across *all* tracked repos, diffing recent commits/PRs against `github_activity_events` to backfill anything a webhook missed.
   - `github-poll-fallback`: `crontab(minute="*/15")` (mirrors Jira's incremental cadence) — but only touches repos where `github_repo_sync_state.sync_mode == 'poll'`. For orgs where every repo got a webhook, this is a fast no-op — directly addressing the "polling in off-hours is pointless" concern, since the frequent job only ever does real work for the subset of repos that couldn't get a webhook.

5. **GitHub client additions** (`apps/api/src/integrations/github/client.py`, currently just `get_user()`/`list_repos()`):
   - `create_webhook(owner, repo, url, secret, events)`, `delete_webhook(owner, repo, hook_id)`
   - `list_commits(owner, repo, since, branch=None, page, per_page)`
   - `list_pull_requests(owner, repo, state="all", since, page, per_page)`

## Frontend changes

- Surface `Task.short_id` on the task card/detail view (roadmap page, e.g. near `apps/web/src/components/roadmap/` — confirm exact component at build time) with a copy-to-clipboard suggested branch name (`feature/AOS-142-short-desc`), so developers know what to reference.
- Optional (not required for MVP): a "Linked GitHub activity" section on task detail showing matched commits/PRs pulled from `github_activity_events`.

## Non-goals

- Storing full commit diffs/patches — only metadata (SHA, message, author, branch, PR title/state) is captured. Revisit only if a future feature needs actual code content.
- GitHub Actions / CI event tracking.
- Multiple GitHub connections per org.

## Verification

1. Migrations apply and roll back cleanly (`alembic upgrade head` / `downgrade -N`).
2. Connect a real org's GitHub OAuth token locally; confirm webhook registration succeeds on an admin-accessible repo (`github_repo_sync_state.sync_mode == 'webhook'`) and falls back gracefully (`sync_mode == 'poll'`) on a repo without admin rights.
3. Push a commit whose message includes a real task's `short_id` to a tracked repo; confirm the webhook fires, a row lands in `github_activity_events`, and the task flips to `IN_PROGRESS`.
4. Open a PR referencing a task's `short_id`, confirm no status change yet; merge it, confirm the task flips to `DONE` with `completed_at` set.
5. Temporarily disable the webhook endpoint, push another referenced commit, confirm it's *not* immediately reflected, then confirm the 15-min poll (for poll-mode repos) or 6h reconciliation sweep (for all repos) backfills it without creating a duplicate `github_activity_events` row.
6. Confirm the dashboard's commit-count query (grouped from `github_activity_events`) returns correct daily totals.
7. Confirm the poll-fallback beat job is a fast no-op for orgs/repos in `'webhook'` mode (validates that off-hours cron isn't burning cycles for no reason).
