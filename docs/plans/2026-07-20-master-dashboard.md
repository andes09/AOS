# Master Dashboard for the Omada Pivot

## Context

Since the Omada pivot to project-roadmap AI, there's no single place to see how the business is doing across all customers/orgs. The user wants an internal, founder-only "master dashboard" tracking three metric families to start: **total users**, **AI cost** (real Anthropic + Groq spend), and **GitHub commit activity** — plus the natural sub-metrics that come with each (signups over time, cost by provider, per-org rollups).

This is explicitly a platform-wide view across *all* orgs, not a per-customer feature — distinct from the existing org-scoped `ExecDashboardPage`. Two of the three metrics don't exist yet in queryable form today:
- **Cost**: currently computed in-memory and only ever written to a log line + a CSV file (`apps/api/sprint_cost_log.csv`), and only for `sprint_plan`/`scope_cop` operations. Groq usage (from the onboarding idea-interview) is captured but never costed — and a bug means its cost would compute as `$0` even if wired up, because `compute_cost()` reads Anthropic-shaped attribute names that don't exist on Groq's usage object.
- **Commits**: the GitHub integration is OAuth-only today (used to grant repo access during onboarding) — no commit/PR data is ever fetched or stored.
- **Total users**: the data already exists (`Developer`, `Organization` tables) — this one just needs a new aggregate query.

There's also no "platform admin" concept yet — all existing roles (`developer`/`lead`/`exec`/`admin`) are per-org. A new cross-org auth check is needed to gate this page to the founder only.

## Decisions made with the user

- **Repo scope for commits**: track all repos visible to each org's connected GitHub OAuth token (no separate allowlist) — in practice each org connects one project repo, so this is already the right scope.
- **Commit backfill window**: first sync per repo starts from when the org's GitHub connection was created, not full repo history.
- **Legacy CSV**: retire `sprint_cost_log.csv` — the new DB table covers everything it did and more.
- **Allowlist mechanism**: Clerk user-ID env allowlist (not email) — no extra Clerk API calls needed, mirrors the existing `allowed_origins` settings pattern.

## Backend changes

### 1. New table `ai_usage_events` — migration `apps/api/alembic/versions/0032_ai_usage_events.py`
Append-only event log (`down_revision = '0031'`). Columns: `id` (UUID PK), `organization_id` (UUID NOT NULL, FK `organizations.id`), `team_id` (UUID NULL, FK `teams.id`), `provider` (`'anthropic'|'groq'`), `operation` (`sprint_plan`/`scope_cop`/`roadmap_generate`/`roadmap_regenerate`/`roadmap_regenerate_milestone`/`idea_interview`), `model`, `input_tokens`, `output_tokens`, `cache_write_tokens`, `cache_read_tokens`, `call_count`, `cost_usd` (**NUMERIC(12,6)**, not float), `context` (JSONB, catch-all for existing free-form kwargs), `created_at` (server_default now()). Indexes on `(organization_id, created_at)`, `(created_at)`, `(provider, created_at)`.

### 2. New table `github_commit_daily` — migration `apps/api/alembic/versions/0033_github_commit_daily.py`
Pre-aggregated daily counts per org+repo (`down_revision = '0032'`), since the goal is dashboard charts, not commit browsing. Columns: `id`, `organization_id` (FK), `repo_full_name`, `date`, `commit_count`, `distinct_author_count` (free "active contributors" sub-metric), `created_at`, `updated_at`. **`UNIQUE (organization_id, repo_full_name, date)`** — the upsert conflict target; each sync run must overwrite counts, never increment, so retries/re-syncs don't double-count. Indexes on `(organization_id, date)` and `(date)`.

### 3. Platform-admin auth — new `apps/api/src/auth_platform.py`
Kept separate from `auth_roles.py` (that module is intrinsically org-scoped; this is a different kind of check). `require_platform_admin` dependency checks `get_current_user_id` (which doesn't require an org claim, unlike `get_current_org_id`) against a new `settings.platform_admin_ids` set. Add to `apps/api/src/config.py`: `platform_admin_user_ids: str = ""` (env `PLATFORM_ADMIN_USER_IDS`, comma-separated Clerk user IDs) + a `platform_admin_ids` computed property, mirroring the existing `allowed_origins` pattern. Empty by default (deny-all until configured).

### 4. New router `apps/api/src/routers/platform_admin.py` (`prefix="/api/platform-admin"`)
Every route behind `Depends(require_platform_admin)`. Register in `main.py` alongside other routers.
- `GET /overview` — `totalOrgs`, `totalUsers` (distinct non-null `Developer.clerk_user_id` across all teams — avoids double-counting one person in two orgs), `cost.allTimeUsd`/`cost.last30dUsd`, `commits.allTime`/`commits.last30d`.
- `GET /signups?range=7d|30d|90d|all` — daily new users/orgs + cumulative users, from `Developer`/`Organization.created_at`.
- `GET /cost?range=...` — daily cost grouped by provider (`anthropicUsd`, `groqUsd`, `totalUsd`) from `ai_usage_events`.
- `GET /commits?range=...` — daily commit counts, summed across orgs, from `github_commit_daily`.
- `GET /orgs` — per-org rollup table: name, slug, created_at, user count, cost (all-time/30d), commits (all-time/30d), onboarding status.

### 5. `cost_tracker.py` rewrite (`apps/api/src/services/cost_tracker.py`)
- Fix the Anthropic/Groq attribute bug: branch `compute_cost` on a new `provider` param — Anthropic keeps today's attribute names + `_PER_MTOK`; Groq gets its own attribute names (`prompt_tokens`/`completion_tokens`, no cache fields) and a new `_GROQ_PER_MTOK` table (**verify current Groq pricing for `llama-3.3-70b-versatile` at build time, don't assume a number**).
- `record_generation_cost` becomes `async def` (currently sync; every call site is already inside an `async def`, so `await`ing it is mechanical) and gains `provider`, `org_id`, `team_id` params.
- DB persistence uses **its own short-lived `AsyncSession`**, never the caller's transaction — if a cost-row insert ever failed mid-flush on the caller's session, it could poison and roll back the actual generation it's supposed to just be logging. Wrapped in its own `try/except` that logs and swallows, preserving the existing "cost tracking must never break a generation" contract.
- Remove the CSV write path entirely (per decision above).
- Update all 5 call sites — each already has the org-bearing object in scope, no new queries needed:
  - `idea_interview.py`: `provider="groq", org_id=session.organization_id`
  - `roadmap_generator.py` (×3 sites): `provider="anthropic", org_id=session.organization_id`
  - `sprint_brain.py`: `provider="anthropic", org_id=team.organization_id`
  - `scope_cop.py`: `provider="anthropic", org_id=org.id`

### 6. GitHub commit sync (Celery)
- `apps/api/src/integrations/github/client.py`: add `list_commits(owner, repo, since, until, page, per_page)` hitting `GET /repos/{owner}/{repo}/commits`, paginated (cap ~20 pages/repo/run).
- New `apps/api/src/integrations/github/commit_sync.py`, mirroring `jira/sync.py`'s shape (sync `Session`, async client bridged via existing event-loop helper, `pg_insert(...).on_conflict_do_update(...)` upsert): `sync_all_orgs_commits()` fans out to `sync_org_commits(organization_id)` per active `GithubConnection`, which lists repos, fetches commits since last-synced date (or since connection creation on first sync), buckets by UTC day, and upserts into `github_commit_daily`.
- Register in `apps/api/src/worker.py`: add to `celery_app`'s `include` list and `beat_schedule` (e.g. daily, offset from Jira's 2am sync).

## Frontend changes

### Routing
Standalone top-level route in `apps/web/src/App.tsx` — **not** nested under `/app`. Confirmed by reading `DashboardLayout`/`OrgProvider`: `DashboardLayout` unconditionally mounts `TeamProvider` (org-scoped `/api/teams` call), and `OrgProvider` requires an active Clerk org and redirects to onboarding if incomplete — neither applies to a cross-org page. New route `/master`, gated only by `<SignedIn>` (same shape as `/app`'s gate, minus `OrgProvider`), rendering `MasterDashboardPage` directly with its own minimal header (title + `ThemeToggle`, no sidebar).

### New files
- `apps/web/src/pages/MasterDashboardPage.tsx` — page shell, range control (7d/30d/90d/All via existing `<SegmentedControl>`), composes the pieces below.
- `apps/web/src/hooks/useMasterDashboard.ts` — `useQuery` wrappers (`useOverview`, `useSignupsSeries`, `useCostSeries`, `useCommitsSeries`, `useOrgRollup`) over `useApi()` from `apps/web/src/lib/api.ts`, following the query-key/hook conventions already used elsewhere (e.g. exec dashboard hooks).
- `apps/web/src/types/masterDashboard.ts` — response types.
- `apps/web/src/components/masterDashboard/OverviewStatRow.tsx` — stat tiles (Total Orgs, Total Users, Cost all-time/30d, Commits all-time/30d), styled like `SectorHealthBanner.tsx`'s big-number pattern.
- `apps/web/src/components/masterDashboard/SignupsChart.tsx`, `CostChart.tsx` (stacked by provider), `CommitsChart.tsx` — `recharts`, following `apps/web/src/components/exec/PlanQualityChart.tsx`'s pattern (hardcoded hex colors since SVG can't read CSS vars). Defer to the `dataviz` skill for exact chart-type/color choices during build.
- `apps/web/src/components/masterDashboard/OrgRollupTable.tsx` — reuses the existing `<Table>` component.

On a 403 from the backend (non-allowlisted user hitting `/master`), show the existing `<Alert variant="danger">` pattern already used elsewhere for `ApiError` — the real access boundary is the backend's `require_platform_admin`, this is just UX.

## Verification

1. **Migrations**: `cd apps/api && alembic upgrade head` applies cleanly; `alembic downgrade -2` and back up to confirm both `upgrade()`/`downgrade()` are correct.
2. **Cost tracking**: trigger a real sprint-plan generation and an onboarding idea-interview chat turn locally; confirm rows land in `ai_usage_events` with correct `provider`/`cost_usd` (Groq row should now be non-zero, confirming the attribute-name bug fix), and confirm a deliberately-broken DB write (e.g. temporarily point at a bad table name) does *not* roll back or fail the underlying generation.
3. **Commit sync**: run `sync_org_commits(<org_id>)` manually (Celery task can be invoked synchronously in a shell) against a real connected GitHub org; confirm `github_commit_daily` rows appear, and running it twice in a row does not double-count (upsert overwrites, not increments).
4. **Auth**: hit `/api/platform-admin/overview` as a non-allowlisted user → expect 403; add your Clerk user ID to `PLATFORM_ADMIN_USER_IDS` locally → expect 200.
5. **Frontend**: run the app locally, sign in as the allowlisted user, navigate to `/master`, confirm stat tiles and all three charts render with real data and the range control re-fetches correctly; sign in as a non-allowlisted user and confirm the access-denied state renders instead of a crash.
