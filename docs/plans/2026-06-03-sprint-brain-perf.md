# Sprint Brain Performance — Execution Plan

**Date**: 2026-06-03  
**Status**: approved, ready to implement  
**Goal**: Cut plan generation latency from ~35s → ~5s perceived, fix broken Jira sync as a prerequisite.

---

## Root causes diagnosed

| Problem | Evidence |
|---|---|
| Jira sync never executes | `celery inspect active` → no workers; tasks queue to Redis, nothing picks them up |
| Scope cop blocks plan return | `_run_plan_pipeline` calls `scope_cop.analyze_tickets` on assigned tickets *before* returning — adds 3-8s to the critical path |
| Complexity analysis re-runs on every plan | Ticket complexity cache only warms on first plan generation; cold starts cost 8-15s |
| Plan generation starts on button click | User waits the full 20-35s after clicking "Generate Plan" |

---

## Codebase reference (verified 2026-06-03)

| Concern | Path | Notes |
|---|---|---|
| Celery worker config | `apps/api/src/worker.py` | broker = `redis://localhost:6379/0`; Redis is up, no workers running |
| Sync task | `apps/api/src/integrations/jira/sync.py:149` | `sync_jira_team` Celery task; sprint-close hooks fired at L237 |
| Manual sync trigger endpoint | `apps/api/src/integrations/jira/router.py:447` | `POST /api/integrations/jira/sync` — calls `.delay()` only; fails silently with no worker |
| Settings sync button | `apps/web/src/pages/SettingsPage.tsx:247` | POSTs to `/api/integrations/jira/sync?team_id=...` |
| Scope cop in plan pipeline | `apps/api/src/routers/sprint_brain.py:649-685` | 35-line block; saves results to `scope_cop_results`; runs before return |
| `_sprint_plan_response` | `apps/api/src/routers/sprint_brain.py:444` | `scopeCopResults` key — starts empty if we strip the auto-run |
| SprintPlannerPage generate | `apps/web/src/pages/SprintPlannerPage.tsx:140` | `generatePlan` useMutation; SSE fetch at L150; button at L377 |
| ScopeCopPanel re-analyze | `apps/web/src/pages/SprintPlannerPage.tsx:286` | `post('/api/scope-cop/analyze', ...)` mutation; already has loading state |
| Ticket complexity service | `apps/api/src/services/sprint_brain.py` | `generate_sprint_plan` → complexity analysis with DB cache; cache keyed on ticket content hash |

---

## Wave 0 — Fix Jira Sync (prerequisite; run first)

**One subagent, unblocks Waves 1B and 1C.**

### SA-0: Fix sync execution

**Problem**: `trigger_sync` calls `sync_jira_team.delay(team_id)`. With no Celery worker, the task sits in Redis forever. User clicks "Sync" in Settings, sees "Sync will begin shortly," nothing happens.

**Fix — two-part:**

**Part A — Make manual trigger run synchronously as primary path.**  
Change `trigger_sync` to call `sync_jira_team` directly (blocking) inside a `BackgroundTask` so FastAPI returns immediately while sync runs in a thread. This makes the Settings sync button reliable regardless of Celery workers.

```python
# apps/api/src/integrations/jira/router.py
from fastapi import BackgroundTasks

@router.post("/sync")
async def trigger_sync(
    team_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
):
    from src.integrations.jira.sync import sync_jira_team
    background_tasks.add_task(sync_jira_team, team_id)  # runs in threadpool
    return {"status": "syncing"}
```

> Note: `sync_jira_team` is a Celery task but is also a plain callable — calling it directly without `.delay()` runs it synchronously in whatever thread calls it. FastAPI's `BackgroundTasks` uses a threadpool, which is safe for the sync DB session inside `sync_jira_team`.

**Part B — Start Celery workers for scheduled syncs (every-15-min incremental).**  
Add to the dev Procfile so workers start automatically:

```
# Procfile (root)
worker: cd apps/api && celery -A src.worker:celery_app worker --loglevel=info -Q celery
beat: cd apps/api && celery -A src.worker:celery_app beat --loglevel=info
```

Also add a `GET /api/integrations/jira/sync-status` endpoint that returns `last_synced_at` from the `JiraConnection` so the frontend can show a real timestamp instead of "Sync will begin shortly."

**Files changed:**
- `apps/api/src/integrations/jira/router.py` — `trigger_sync` + new `sync_status` endpoint
- `Procfile` (create if absent) or `README.md` — worker startup
- `apps/web/src/pages/SettingsPage.tsx` — poll `sync-status` after triggering sync; show last synced timestamp

**Exit gate**: click "Sync" in Settings → `last_synced_at` updates within 30s, tickets appear in DB.

---

## Wave 1 — Performance (3 subagents in parallel; Wave 0 must be complete for 1B)

### SA-1A: Remove scope cop from planning critical path

**Saves 3-8s. Fully independent of Wave 0.**

**Backend** (`apps/api/src/routers/sprint_brain.py`):
- Delete lines 649-685 (the `scope_cop_ran_at` / `scope_cop_results` auto-run block)
- Remove `scope_cop_ran_at` and `scope_cop_results` from `_sprint_plan_response` call at L701
- Keep `scopeCopRanAt: null` and `scopeCopResults: []` as static defaults in `_sprint_plan_response` so the response shape doesn't change
- Remove unused `scope_cop` import if it becomes unused

**Frontend** (`apps/web/src/pages/SprintPlannerPage.tsx`):
- After `generatePlan` succeeds and `setPlan(...)` is called, immediately fire the scope cop analyze mutation in the background
- ScopeCopPanel already handles the loading/populated states — no UI changes needed
- When analyze completes, merge results into plan state so `scopeCopResults` populates

```typescript
// After generatePlan onSuccess:
onSuccess: (data) => {
  setPlan(data)
  // fire scope cop in background — results populate into panel ~5s later
  scopeAnalysisMutation.mutate()
}
```

**Files changed:**
- `apps/api/src/routers/sprint_brain.py` — remove scope cop block
- `apps/web/src/pages/SprintPlannerPage.tsx` — auto-trigger analyze on plan success; merge results into plan state

**Exit gate**: plan returns in < 1s after Claude finishes; ScopeCopPanel populates a few seconds later without user action.

---

### SA-1B: Pre-compute ticket complexity after Jira sync

**Eliminates the 8-15s complexity stage on cache miss. Depends on Wave 0 (sync must work).**

**New Celery task** (`apps/api/src/integrations/jira/sync.py`):

```python
@celery_app.task
def prewarm_ticket_complexity(team_id: str) -> None:
    """Run complexity analysis on backlog tickets after sync to warm the cache."""
    import asyncio
    from src.database import AsyncSessionLocal
    from src.services.sprint_brain import _prewarm_complexity

    async def _run():
        async with AsyncSessionLocal() as db:
            await _prewarm_complexity(team_id, db)

    asyncio.get_event_loop().run_until_complete(_run())
```

**Hook into `sync_jira_team`** — after the final `db.commit()` at line 231, before sprint-close hooks:

```python
# After db.commit() at line 231:
try:
    prewarm_ticket_complexity.delay(team_id)
except Exception:
    pass  # never block sync completion
```

**New `_prewarm_complexity` helper** (`apps/api/src/services/sprint_brain.py`):
- Calls `_get_candidate_tickets` to fetch the current backlog
- Runs complexity analysis on all tickets not already in the cache
- Cache check: skip tickets whose content hash already exists in `ticket_complexity_cache` table

**Files changed:**
- `apps/api/src/integrations/jira/sync.py` — new `prewarm_ticket_complexity` task + hook
- `apps/api/src/services/sprint_brain.py` — `_prewarm_complexity` helper
- `apps/api/src/worker.py` — add `prewarm_ticket_complexity` to `include` list

**Exit gate**: after a manual sync, complexity cache entries exist in DB for backlog tickets; next plan generation logs `[sprint-brain] complexity cache hit` for all tickets.

---

### SA-1C: Pre-warm plan generation on SprintPlannerPage mount

**Hides remaining latency — plan is ready when user clicks. Independent of all other waves.**

**Approach**: On mount, silently start the SSE stream. Store result in a ref. "Generate Plan" button shows the cached result immediately if pre-warm is done, or reveals the already-in-progress stream if still running.

```typescript
// apps/web/src/pages/SprintPlannerPage.tsx

const prewarmRef = useRef<{ status: 'pending' | 'done' | 'error'; data?: SprintPlanResponse }>({ status: 'pending' })
const prewarmAbort = useRef<AbortController | null>(null)

useEffect(() => {
  if (!teamId || plan) return  // don't prewarm if plan already shown

  const ctrl = new AbortController()
  prewarmAbort.current = ctrl

  // Silently start SSE stream
  startPlanStream({ signal: ctrl.signal }).then(data => {
    prewarmRef.current = { status: 'done', data }
  }).catch(() => {
    prewarmRef.current = { status: 'error' }
  })

  return () => ctrl.abort()
}, [teamId])

// On button click:
function handleGeneratePlan() {
  if (prewarmRef.current.status === 'done' && prewarmRef.current.data) {
    setPlan(prewarmRef.current.data)        // instant
    scopeAnalysisMutation.mutate()          // kick off scope cop
  } else {
    generatePlan.mutate()                   // normal SSE path (already ~15s ahead)
  }
}
```

**Edge cases to handle:**
- User navigates away before clicking → abort controller cancels the stream
- Pre-warm errors → fall through to normal generation, no visible difference
- User already has a plan shown (re-generate scenario) → skip pre-warm, go straight to normal generation
- Team has no tickets yet → pre-warm will 422; catch silently, fall through

**Files changed:**
- `apps/web/src/pages/SprintPlannerPage.tsx` — mount effect, prewarmRef, handleGeneratePlan logic

**Exit gate**: click "Generate Plan" → plan appears in < 500ms (pre-warm hit); or within 5s (pre-warm still in progress). No regression on error/empty-backlog paths.

---

## Execution order

```
Wave 0 (SA-0)          ──► fix sync, start workers
     │
     ├── SA-1A (parallel) ──► remove scope cop from critical path
     ├── SA-1B (parallel) ──► complexity prewarm on sync
     └── SA-1C (parallel) ──► frontend pre-warm on mount
```

Wave 1 subagents SA-1A and SA-1C can start immediately (no sync dependency). SA-1B must wait for Wave 0 exit gate.

## Expected latency after all waves

| Stage | Before | After |
|---|---|---|
| Complexity analysis | 8-15s (cold) / ~0 (warm) | ~0 always (pre-warmed by sync) |
| Assignment (Claude) | 8-15s | 8-15s (hidden by page pre-warm) |
| Scope cop | 3-8s | 0s on critical path (async) |
| **Perceived on button click** | **~35s** | **< 1s (pre-warm hit) or ~5s (miss)** |
