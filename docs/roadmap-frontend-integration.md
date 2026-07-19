# Roadmap — frontend integration guide

This is for whoever builds the real roadmap UI (the project → milestones →
tasks calendar/plan view). The backend and a small headless React layer are
done; this doc is everything you need to build against them without reading
the API source.

**TL;DR:** import hooks from `apps/web/src/features/roadmap`, don't call
`fetch` yourself, and render from `state.status` — the layer owns auth,
optimistic updates, rollback, and cache consistency.

## What already exists

- **API**: `apps/api/src/routers/roadmap.py`
- **Headless layer** (your integration surface): `apps/web/src/features/roadmap/`
  - `types.ts` — the API shapes (source of truth, kept in lockstep with the
    backend by `apps/api/tests/test_roadmap.py`)
  - `api.ts` — framework-agnostic client (`createRoadmapApi`)
  - `hooks/` — React Query hooks (what you'll actually use)

You should never need to touch the backend or call `fetch` directly — the
hooks handle auth (Clerk bearer token), error shapes, optimistic updates, and
cache reconciliation for you.

## The data model

One roadmap per org, generated from the onboarding brief:

```
RoadmapProject { id, name, summary, purpose, milestones[] }
  └─ RoadmapMilestone { id, title, description, sortOrder, tasks[] }
       └─ RoadmapTask { id, title, description, status, sortOrder, scheduledDate }
```

- `status` is `'todo' | 'in_progress' | 'done'` — the user flips it to check
  things off.
- `scheduledDate` is a `"YYYY-MM-DD"` string (or null = unscheduled) — this is
  what the calendar view plots.
- `sortOrder` is 0-based and contiguous within its parent; milestones and
  tasks arrive already sorted.

## The state machine

Everything renders from one hook:

```tsx
import { useRoadmap } from '../features/roadmap'

const { state, generate, regenerate, regenerateMilestone, regeneratingMilestoneId } =
  useRoadmap()
```

`state` is a discriminated union — switch on `state.status`:

```
loading ──▶ empty ──generate.mutate()──▶ generating ──▶ ready
                                             │            │
                                             ▼            │ regenerate.mutate()
                                           error ◀────────┘   (back to generating)
```

| status       | you render                                | extras on `state`          |
| ------------ | ----------------------------------------- | -------------------------- |
| `loading`    | skeleton                                  | —                          |
| `empty`      | "plan my project" CTA → `generate.mutate()` | —                        |
| `generating` | progress/loading treatment                | `project` (stale tree or null) |
| `ready`      | the roadmap                               | `project`                  |
| `error`      | error banner (+ stale tree if present)    | `error`, `project`         |

Notes:

- **Generation is one long HTTP call** (an LLM plans the roadmap — expect tens
  of seconds). `generating` simply means the call is in flight; when it
  resolves, `state` flips straight to `ready` with the new tree already in the
  cache. Keep the user on the page; show a real "planning your project…"
  treatment, not a spinner that looks stuck.
- While the roadmap is still `empty`, the hook **polls every 5s** (configurable:
  `useRoadmap({ pollIntervalMs })`) so a roadmap generated elsewhere — another
  tab, or the tail end of onboarding — appears without a reload.
- During a **regenerate**, `state.project` still holds the previous tree — dim
  it rather than blanking the screen.
- `regenerateMilestone.mutate(milestoneId)` replans just that milestone's
  tasks; while it runs, `regeneratingMilestoneId` tells you which one to put a
  spinner on. The rest of the tree stays interactive.
- After a failed mutation, `state.status` is `'error'` until you `.reset()`
  the mutation (e.g. `generate.reset()`) or a retry succeeds — wire your
  "dismiss" / "try again" buttons accordingly.
- `generate` is **idempotent** — if a roadmap already exists the server
  returns it unchanged, so double-clicks are harmless. `regenerate` is the
  destructive one: it throws the current plan away. Put a confirm on it.

## Task edits (all optimistic)

```tsx
import { useTaskMutations } from '../features/roadmap'

const { updateTask, deleteTask, setTaskStatus } = useTaskMutations()

setTaskStatus(task.id, 'done')                                  // check off
updateTask.mutate({ taskId, patch: { title: 'New title' } })    // retitle
updateTask.mutate({ taskId, patch: { scheduledDate: '2026-08-01' } }) // reschedule
updateTask.mutate({ taskId, patch: { scheduledDate: null } })   // unschedule
updateTask.mutate({ taskId, patch: { sortOrder: 2 } })          // reorder in milestone
deleteTask.mutate(taskId)                                       // delete
```

Every edit updates the cached tree **instantly** and rolls back automatically
if the server rejects it — you never wait on the network to reflect a
check-off or a drag. Semantics worth knowing:

- The patch is sparse: only fields you send change. `null` is meaningful for
  `scheduledDate` (unschedule) and `description` (clear).
- `sortOrder` is the target index (0-based) **within the task's milestone**;
  siblings reshuffle to stay contiguous, mirrored optimistically and then
  reconciled with a background refetch. Moving tasks *between* milestones is
  not supported by the API today.
- Validation (e.g. title 1–255 chars, status enum) is server-side and
  surfaces as `updateTask.error.message` — after a rejection the optimistic
  change has already been rolled back, so just show the message.

## Errors you should expect

All client methods throw `RoadmapApiError` with a `.status`:

- **409 on `generate`/`regenerate`** — onboarding hasn't produced a project
  brief yet. Route the user to onboarding.
- **402 on `generate`/`regenerate`** — no Anthropic API key available (org
  BYOK key missing and no platform fallback). Show the message.
- **502 on `generate`/`regenerate`** — the model call failed; safe to retry.
- **404 on task mutations** — the task vanished (deleted elsewhere or after a
  regenerate); the rollback already restored your view, refetch via
  `refresh()` if it keeps happening.
- A 409 `org_not_provisioned` on the initial read self-heals (the hook
  provisions the org and retries) — you'll never see it.

## Local setup

1. `apps/api/.env` needs `ANTHROPIC_API_KEY` (see root `.env.example`) —
   generation falls back to the platform key before an org saves its own.
2. Run the API (`apps/api`) and the web app (`pnpm dev:web`); the layer
   points at `VITE_API_URL` (defaults to `http://localhost:8000`).
3. Generation needs a completed onboarding brief — run through the
   onboarding v2 flow once (see
   `docs/onboarding-v2-frontend-integration.md`), then `generate.mutate()`.
4. `VITE_TEST_MODE=true` lets the client send a dummy bearer token for
   Playwright / mocked-API poking, same as onboarding.

## Rules of the road

- **Only import from `apps/web/src/features/roadmap`.** Never call
  `fetch('/api/roadmap/...')` yourself — the hooks own auth, error parsing,
  optimistic updates, and rollback, and a raw fetch will fight the cache.
- **Don't guess field names from memory** — `types.ts` in that folder is the
  source of truth, kept in lockstep with the backend by
  `apps/api/tests/test_roadmap.py`.
- **Render from `state.status`, not from ad-hoc booleans** — the union is
  exhaustive, so a `switch` gives you compiler coverage when states are added.
- **Don't reimplement reorder math.** Send the target index; the layer and
  server both keep `sortOrder` contiguous.
- If you need a field or endpoint that isn't here (e.g. moving a task between
  milestones, editing milestone titles), ask rather than adding a raw fetch
  call — the API is deliberately small and the layer should grow with it.
