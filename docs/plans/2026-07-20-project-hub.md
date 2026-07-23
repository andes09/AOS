# Project Hub — multi-project support, org project cap, Active/Finished/Archived

## Context

Omada today is single-project-per-org everywhere it matters. `Project.onboarding_session_id` (`apps/api/src/models/project.py:16-18`) is a **unique** FK to `onboarding_sessions.id`, and `OnboardingSession.organization_id` (`apps/api/src/models/onboarding_session.py:27-29`) is **also unique** — so an org can have at most one `OnboardingSession`, which can produce at most one `Project`. Every roadmap endpoint (`apps/api/src/routers/roadmap.py`) and the org-onboarding endpoints (`apps/api/src/routers/onboarding_v2.py`) hard-code this by resolving "the org's session" via `db.scalar(select(OnboardingSession).where(OnboardingSession.organization_id == org.id))` — a single-row assumption with no `ORDER BY`. Once a second row can exist, `.scalar()` (effectively `.first()`) would silently return an arbitrary row instead of erroring — this is the central hazard the plan has to close, not a hypothetical one.

The good news, confirmed by reading `apps/api/src/services/idea_interview.py` and `roadmap_generator.py` in full: the brief-gathering machinery is **already parametrized by an explicit `OnboardingSession` object** end to end. Only the router layer added the "assume one session per org" lookup. That means "create project #2" is mechanically "create a new `OnboardingSession` row and drive it through the same chat/generate services a second time" — not a new parallel system.

The user wants a Project Hub: a page listing all of an org's projects grouped into **Active / Finished / Archived**, where clicking a project opens its roadmap/timeline. This becomes the new `/app` landing page, replacing today's `index → Navigate to="roadmap"` redirect (`App.tsx:50`).

`docs/plans/2026-07-20-import-artifacts.md` (not yet implemented) documents a future chat-vs-import chooser and `onboarding_path` field for org onboarding. That plan's code doesn't exist yet. This plan builds the multi-project skeleton so import-based project creation slots in later without rework, but ships **chat-only creation now**.

## Decisions

Confirmed with the user:
1. **True multi-project per org** — real independent `Project` rows, not history/snapshots.
2. **A configurable, nullable `max_projects` cap** per org, enforced at creation time (useful for future plan/tier gating).
3. **New-project creation reuses the onboarding brief flow** (chat now, import later), decoupled from org onboarding — not a bare manual form.
4. **"Finished" is a manual status transition only** — never derived from task completion.
5. **Project Hub replaces the `/app` index route.** Roadmap/Planner become project-scoped nested routes.

Decided during design, consistent with the above and existing repo conventions:
- **What counts against `max_projects`**: all projects regardless of status (active + finished + archived). The repo has no soft-delete pattern; archiving is a visibility flag, not a resource-freeing operation, so it must not be a loophole around the cap.
- **Valid status transitions**: `active ↔ finished`, `active ↔ archived`, `finished → archived`. **Not allowed**: `archived → finished` directly (must restore to active first) — keeps every transition a single explicit user intent.
- **`max_projects` lives on `Organization`** (tenant/billing-tier concept, same level as `encrypted_anthropic_key`/`use_managed_key`), not `Team`.

## Backend changes

### 1. Migration `apps/api/alembic/versions/0032_project_hub.py` (`down_revision = '0031'`)

*Note: `docs/plans/2026-07-20-master-dashboard.md` and `docs/plans/2026-07-20-import-artifacts.md` also reserve `0032`/`0033`, neither implemented yet — whichever plan lands first claims the number, the others rebase.*

- `projects.status` — `String(20)`, `nullable=False`, `server_default='active'`. New `ProjectStatus` enum in `project.py` (`ACTIVE`/`FINISHED`/`ARCHIVED`) as the value source only — plain string column, **not** a native Postgres enum, matching `Task.status`/`TaskStatus` (`apps/api/src/models/task.py:11-14`).
- `organizations.max_projects` — `Integer`, `nullable=True`. `NULL` = unlimited.
- Drop the unique constraint on `onboarding_sessions.organization_id` (`op.drop_constraint(..., type_='unique')`). **Keep** the separate plain index that already exists on that column (added alongside the unique constraint in `0027_onboarding_v2.py`) — it's exactly what the now-multi-row lookups need.
- `downgrade()`: recreate the unique constraint (document that this only works cleanly if no org has >1 session at downgrade time — same caveat style other migrations use), drop the two new columns.

`Project` already has `name`, `summary`, `created_at`, `updated_at` — sufficient for hub cards, no other new columns needed.

### 2. Fix `onboarding_v2.py`'s session lookup so it keeps meaning "the founding session"

`_get_session`/`_get_or_create_session`/`_build_state` (`onboarding_v2.py:74-111`) currently do `select(OnboardingSession).where(organization_id == org.id)` with no ordering. Add `.order_by(OnboardingSession.created_at.asc())` (or `.limit(1)`) so org onboarding always resolves to the *first* session ever created, even after project-creation sessions exist. `OrgProvider.tsx`'s onboarding gate is keyed off `Organization.onboarding_completed_at`, not session count — unaffected.

### 3. New router `apps/api/src/routers/projects.py` (`prefix="/api/projects"`)

Shared helpers extracted to `apps/api/src/routers/project_common.py` (same "used twice → extract" rule the import-artifacts plan already applied to `roadmap_shapes.py`): `_get_org` and a new `_owned_project(project_id, org, db)` — loads `Project` by PK with a `join(Team).where(Team.organization_id == org.id)` check, 404 otherwise, eager-loading milestones/tasks and `onboarding_session`. `roadmap.py` imports this instead of keeping its own `_load_project`.

Endpoints:
- **`GET /api/projects`** — all of the org's projects, optional `?status=` filter. Response: `{id, name, summary, purpose, status, createdAt, updatedAt, hasRoadmap}`. Hub groups Active/Finished/Archived client-side from one call.
- **`GET /api/projects/{project_id}`** — single project metadata (lightweight header for roadmap/planner pages).
- **`POST /api/projects`** — starts project creation. Enforces the cap (`count(*) across all statuses` vs `org.max_projects`) → `422 project_limit_reached` if hit. Otherwise creates a new `OnboardingSession(organization_id=org.id, status="in_progress")`, returns `{sessionId}`.
- **`PATCH /api/projects/{id}`** — body `{name?, status?}`, combinable in one call (`model_fields_set` pattern like `TaskUpdateRequest`). Illegal status transition → `409 invalid_status_transition`.

Creation sub-resource, prefixed `/api/projects/sessions/{session_id}`, with its own `_owned_session` ownership check (session, not project — no `Project` exists yet):
- **`PUT /sessions/{id}/purpose`** — mirrors `onboarding_v2.py`'s `PUT /purpose`.
- **`GET /sessions/{id}/chat`**, **`POST /sessions/{id}/chat/message`** — thin wrappers into `idea_interview.run_interview_turn` (unchanged service, same SSE pattern as `roadmap.py`'s existing chat endpoints).
- **`POST /sessions/{id}/generate`** — re-checks the cap, resolves the org's team, calls `roadmap_generator.generate_roadmap(session, team, api_key, db)` (unchanged signature), returns the new `Project`. Frontend navigates to `/app/projects/{id}/roadmap` on success.

This deliberately does not reuse `onboarding_v2.py`'s endpoints — it skips `github_connect`/`profile` (already satisfied at the org level) and starts at purpose → chat → generate, which is the "decoupled" part of decision 3.

**Import-artifact creation is explicitly out of scope for this plan** — it's a fast-follow once `docs/plans/2026-07-20-import-artifacts.md` ships `artifact_import.py`/`roadmap_shapes.py`, adding a parallel `/sessions/{id}/import/analyze`+`/apply` pair under the same prefix.

### 4. `roadmap.py` rework — explicit `project_id`, one URL convention

New prefix: `/api/projects/{project_id}/roadmap`, applied to every existing sub-route (`""`, `/members`, `/generate`, `/regenerate`, `/milestones/{id}/regenerate`, `/tasks`, `/tasks/reschedule`, `/tasks/{id}` PATCH+DELETE, `/status`, `/chat`, `/chat/message`). FastAPI matches path params by name whether declared in the router prefix or the route decorator, so each function just gains `project_id: uuid.UUID`.

Key per-endpoint changes:
- **`get_roadmap`**: `project = await _owned_project(project_id, org, db)` → `_project_json(project)` directly (add `status` to `_project_json`). 404 replaces the old "session is None → return None" branch.
- **`get_members`**: stays org-scoped for *which developers* are listed, but the `scheduled_count` subquery (`roadmap.py:275-284`) currently counts a developer's scheduled tasks **across the whole org** — with multiple projects this conflates unrelated projects' workloads into one badge. Scope it to `Milestone.project_id == project_id`. Real behavior fix, not just a rename.
- **`generate`**: now only reachable for a project that already exists in the URL — becomes a narrow repair/idempotency endpoint (return as-is if milestones exist, else regenerate from `project.onboarding_session`). The "create a brand-new project" path moves entirely to `POST /sessions/{id}/generate`.
- **`_owned_task`, `_owned_milestone`, `_owned_tasks`** (`roadmap.py:145-198`, `207-222`): **must add a `Milestone.project_id == project.id` filter**, not just the org check. This is a real cross-tenant-*within-org* gap the multi-project change introduces: a client could pass a valid `project_id` for project A but a `task_id` belonging to sibling project B in the same org — an org-only check would wrongly authorize it. Since `_owned_project` already validated `project_id` against the org, these helpers take the loaded `project` and filter on it directly.
- **`_session_and_brief`, `_get_or_create_session`**: removed — replaced by `project.onboarding_session` off the already-loaded `Project` (still 1:1 on the `Project` side).
- **`get_status`, `get_chat`, `chat_message`**: resolve via `_owned_project`, operate on `project.onboarding_session`.

### 5. Tests

`apps/api/tests/test_roadmap.py` needs real rework, not find/replace: every `POST /api/roadmap/...` becomes `POST /api/projects/{project.id}/roadmap/...`, plus a new cross-project 404 test class (task/milestone from project A must 404 through project B's URL, same org — the exact gap fixed above). New `apps/api/tests/test_projects.py`: list/group by status, cap enforcement, valid/invalid transitions, rename, full session-scoped creation flow. Extend `test_onboarding_v2.py` with a case seeding 2+ sessions for one org, confirming `_get_session`/`_build_state` resolve to the earliest.

## Frontend changes

### Routing — `apps/web/src/App.tsx`

Replace `<Route index element={<Navigate to="roadmap" replace />} />` with `<Route index element={<ProjectHubPage />} />`. Nest project-scoped routes:
```
<Route path="projects/:projectId/roadmap" element={<RoadmapPage />} />
<Route path="projects/:projectId/sprint-planner" element={<PlannerPage />} />
```
Bare `roadmap`/`sprint-planner` routes removed. Unaffected (confirmed): `velocity-mirror`, `exec-dashboard`, `dependency-radar`, `retrospective`, `multi-team`, `settings*` — none reference a project id.

### New `apps/web/src/features/projects/` (mirrors `features/roadmap/` convention)
- `types.ts` — `ProjectSummary { id, name, summary, purpose, status, createdAt, updatedAt, hasRoadmap }`.
- `api.ts` — `listProjects()`, `getProject(id)`, `startProjectCreation()`, `setCreationPurpose()`, creation-chat calls, `generateFromSession()`, `updateProject(id, patch)`.
- `hooks/useProjects.ts` — `useQuery(['projects'], ...)` + status/rename mutations invalidating that key.
- `hooks/useProjectCreation.ts` — wraps start → purpose → chat → generate as a small state union (`idle → purposeChosen → chatting → generating → done(projectId) → error`), same shape `RoadmapState` already uses.

### New pages
- `apps/web/src/pages/projects/ProjectHubPage.tsx` — Active/Finished/Archived sections from `useProjects()`, "New Project" entry point.
- `apps/web/src/pages/projects/ProjectCard.tsx` — status-appropriate actions (`Mark finished`/`Archive`/`Reopen`/`Restore`), only ever offering legal transitions; navigates to `/app/projects/{id}/roadmap`.
- `apps/web/src/pages/projects/ProjectCreateModal.tsx` (or its own `/app/projects/new` route — simpler given the multi-step flow benefits from refresh-safety) — reuses existing `apps/web/src/pages/onboarding-v2/steps/PurposeStep.tsx` and `IdeaChatStep.tsx` for presentation (both take callback props already, not org-implicit hooks internally, so this is genuine minimal-diff reuse), rewired to `useProjectCreation`'s session-explicit calls instead of `useOnboardingState()`. On generate success, navigate to the new project's roadmap and invalidate `['projects']`.

### Threading `projectId` through existing roadmap/planner code

Three separate places currently hardcode `/api/roadmap/*` and all need the same change:
- **`apps/web/src/features/roadmap/api.ts`** (used by `RoadmapPage`) — `createRoadmapApi` gains `projectId`; every path becomes `/api/projects/${projectId}/roadmap...`. `hooks/useRoadmapApi.ts` reads `projectId` via `useParams()`. `hooks/useRoadmap.ts`'s `ROADMAP_KEY` becomes `['roadmap', projectId]`.
- **`apps/web/src/pages/planner/usePlannerData.ts`** + **`usePlannerMutations.ts`** — a second, independent client hitting the same endpoints directly via `useApi()` (confirmed: `ROADMAP_KEY`/`MEMBERS_KEY`, lines 21-22, and every literal path in `usePlannerMutations.ts` lines 59/66/74/81/104). Both need `projectId` from `useParams()` threaded into every path and query key.
- **`apps/web/src/pages/planner/useProjectChat.ts`** — a third, independently-hardcoded client (raw `fetch` to `/api/roadmap/chat` and `/api/roadmap/chat/message` at lines 30/61, confirmed) — easy to miss since it bypasses both `useApi()` and the `features/roadmap` barrel entirely. Needs `projectId` in both URLs too.

### `DashboardLayout.tsx` — sidebar becomes project-aware

Nav links `/app/roadmap` and `/app/sprint-planner` (confirmed at lines 92/97) become `/app/projects/${projectId}/roadmap` / `/app/projects/${projectId}/sprint-planner`, `projectId` read via `useParams()` (works since the sidebar renders inside the same `DashboardLayout` that hosts the nested project routes via `Outlet`). Add a lightweight "back to hub" link/project-name breadcrumb above the nav items. `TeamSwitcher` unaffected.

## Verification

1. **Migrations**: `cd apps/api && alembic upgrade head` applies cleanly; `alembic downgrade -1` and back up.
2. **Backend tests**: `pytest tests/test_roadmap.py tests/test_projects.py tests/test_onboarding_v2.py` — reworked roadmap tests green under new URL shape; new cross-project 404 tests pass; cap enforcement and status-transition validation covered; onboarding "earliest session wins" case passes with 2+ sessions.
3. **Manual — creation and independence**: land on `/app`, see `ProjectHubPage` (existing single project under Active); create a 2nd project via the chat flow; confirm both projects' roadmaps are fully independent (edits to one never touch the other).
4. **Manual — cap**: set `Organization.max_projects` to the org's current count; confirm `POST /api/projects` returns 422 and the Hub surfaces that message cleanly.
5. **Manual — status lifecycle**: Mark Finished → moves Active→Finished section without full reload; Archive → moves to Archived; Restore → back to Active; confirm `archived → finished` isn't offered directly.
6. **Regression**: `velocity-mirror`/`exec-dashboard`/`retrospective`/`multi-team`/`settings*` routes unaffected; org-founding `/onboarding` flow still completes correctly for a brand-new org.
7. **Import-artifact fast-follow**: confirm no import-based creation ships in this change, and that the `/api/projects/sessions/{id}/...` prefix is shaped so that plan can add `/import/analyze`+`/apply` later without touching this plan's endpoints.

### Critical files
- `apps/api/src/routers/roadmap.py`, `apps/api/src/routers/onboarding_v2.py`
- `apps/api/src/models/project.py`, `apps/api/src/models/onboarding_session.py`, `apps/api/src/models/organization.py`
- `apps/web/src/App.tsx`, `apps/web/src/layouts/DashboardLayout.tsx`
- `apps/web/src/features/roadmap/api.ts`, `apps/web/src/pages/planner/usePlannerData.ts`, `usePlannerMutations.ts`, `useProjectChat.ts`
- `apps/web/src/pages/onboarding-v2/steps/PurposeStep.tsx`, `IdeaChatStep.tsx` (reused, not modified)
