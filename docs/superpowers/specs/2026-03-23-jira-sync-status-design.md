# Jira Sync Status Tracking — Design Spec

**Date:** 2026-03-23
**Branch:** feat/background-sync
**Status:** Approved

## Context

AgileOS already has a fully functional background Celery/Redis sync pipeline (`worker.py`, `sync.py`). The remaining gaps are:

1. No persistent sync status visible to the frontend
2. No API endpoint to query sync state
3. No Railway worker service config

This spec covers only those four missing pieces. The existing worker, beat schedule, and task logic are not changed.

## What We're Building

### 1. `jira_sync_statuses` table

Single-row-per-team upsert model. One row represents the current sync state for that team.

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `team_id` | UUID (PK, FK → teams) | One row per team |
| `status` | Enum | `pending \| running \| success \| failed` |
| `last_synced_at` | DateTime, nullable | Set on success |
| `error` | Text, nullable | Last failure message |
| `updated_at` | DateTime | Updated on every transition |

**Migration:** `0003_add_jira_sync_status.py`

### 2. Status transitions in `sync_jira_team`

Transitions written to `jira_sync_statuses` at each stage:

- **At `.delay()` call time** (router + board-selection): upsert `pending`
- **Task start**: upsert `running`
- **Task success**: upsert `success`, set `last_synced_at = now`, clear `error`
- **Task final failure** (retries exhausted): upsert `failed`, set `error = str(exc)`

The `pending` write at enqueue time gives the frontend immediate feedback before the worker picks up the task.

### 3. API endpoint

```
GET /api/integrations/jira/sync-status/{team_id}
```

- Auth: `get_current_user_id` dependency
- Returns: `{ team_id, status, last_synced_at, error }`
- 404 if no row exists (team has never been synced)

Added to `apps/api/src/integrations/jira/router.py`.

### 4. Railway worker service config

`apps/api/railway-worker.toml` — separate Railway service running the Celery worker + beat:

```toml
[deploy]
startCommand = "sh -c 'celery -A src.worker worker --beat --loglevel=info'"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 5
```

No `preDeployCommand` — migrations run on the web service only.

## What We're NOT Changing

- `worker.py` beat schedule (daily full + every-15-min incremental is already better than the spec's 6-hour suggestion)
- `sync.py` task logic (already correct)
- Board-selection and `POST /sync` trigger pattern (already calls `.delay()`)
- Redis/Celery config (already wired to `settings.redis_url`)

## Files Touched

| File | Change |
|---|---|
| `src/models/jira_sync_status.py` | New model |
| `src/models/__init__.py` | Import new model |
| `alembic/versions/0003_add_jira_sync_status.py` | New migration |
| `src/integrations/jira/sync.py` | Add status writes to `sync_jira_team` |
| `src/integrations/jira/router.py` | Add status endpoint + pending writes |
| `apps/api/railway-worker.toml` | New file |
