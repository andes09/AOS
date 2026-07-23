# GitHub-Driven Task Auto-Complete (event-driven, not pure cron)

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
