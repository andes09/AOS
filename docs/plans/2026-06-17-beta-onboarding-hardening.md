# Beta-Ready: Harden Jira Onboarding → First Sprint Plan

## Context

Omada is preparing for a beta release. Production feature flags (`apps/api/config/features/production.yaml`) keep most of the product surface dark — beta effectively is the **Jira OAuth → board pick → sync → confirm team → first sprint plan** flow. Git history confirms this flow is the production risk: 16 of the last 20 commits are fixes on this single path ("surface silent failures from in-process Jira sync," "Python 3.12 event loop," "Celery broker," "OAuth trailing slash," "[object Object] errors," "fix restart loop when confirm-team fails"). There are still uncommitted edits on `jira/push.py`, `jira/router.py`, `jira/sync.py`, and the models.

Three structural problems sit behind that pattern:

1. **No automated coverage** of the flow. Backend tests exist (`apps/api/tests/` uses pytest + `tmp_db` + `_patch_clerk`), but no test stitches OAuth → boards → sync → confirm-team → `/plan` together. The web app has **zero** test framework, and there is **no CI workflow** anywhere in the repo — so even the existing backend tests don't gate PRs.
2. **Silent failures** at known hotspots: `router.py:318-355` (boards swallows errors and returns `[]`), `sync.py:40-41/155-156/164-165` (bare `except: pass`), and `_run_sync_in_process` (`router.py:43-61`) which catches everything but never resurfaces to the user.
3. **No recovery path** when the flow dead-ends. `OnboardingPage.tsx:640` fetches the team list once in `ConnectFlow` and reuses it stale in `ConfirmTeam`; a 502 from `/team-members` hard-blocks the user (`router.py:438-440`); there is no "reset connection / retry" UX. `JiraSyncControl.tsx:74-77` shows a generic "Sync failed" with no detail extraction.

The intended outcome is that a beta user can complete onboarding end-to-end, that any failure is visible to both the user and to us, that a stuck user can recover without engineering intervention, and that the test that proves this gates every PR.

## Goals

1. A backend pytest e2e covering OAuth callback → boards → board-selection → sync → team-members → confirm-team → `/api/sprint-brain/plan`, with mocked Jira HTTP — gating every PR.
2. A Playwright smoke driving the actual React onboarding UI against a backend with mocked Jira, catching frontend dead-end regressions.
3. Structured logging + a `SyncStatus` table + frontend polling, so the UI knows when sync finishes and what failed.
4. Sentry on both FastAPI and React for real-time alerting during beta.
5. A `/api/onboarding/reset` endpoint and Reset button on `ConfirmTeam` / `Boards` to unstick users without DB surgery.
6. A GitHub Actions workflow running pytest + Playwright on every PR into `main`.

## Execution: parallel work streams

Five streams. **Streams A, B, D, E are independent and run in parallel from the start. Stream C depends on B (needs `SyncStatus` endpoint + error.detail shape). Stream F (CI) depends on A and C finishing.** Fan out one Agent per stream.

```
t=0 ─┬─ Stream A: Backend e2e pytest                              ┐
     ├─ Stream B: Backend observability + sync_status + Sentry    ┤
     ├─ Stream D: Backend reset endpoint                          ├─→ Stream F: CI workflow
     └─ Stream E: Fix silent-failure hotspots                     ┘
                                ↓
                  Stream C: Frontend (error surfacing,
                  polling, Reset button, Sentry, Playwright)
```

---

### Stream A — Backend e2e test (Agent: `e2e-backend`)

**Goal:** One pytest that exercises the full flow with mocked Jira HTTP, runs in seconds, fails loudly on the regressions of the last 20 commits.

- New file: `apps/api/tests/test_onboarding_flow_e2e.py`.
- Reuse `tmp_db` fixture and `_patch_clerk(user_id, org_id)` pattern from `apps/api/tests/test_jira_router.py`.
- Reuse the `AsyncMock(httpx.AsyncClient)` pattern from `apps/api/tests/test_track4_jira_push.py` to stub `JiraClient.get_boards`, `get_projects`, `get_users`, `get_board_sprints`, `get_board_backlog`.
- Test steps:
  1. Seed `OAuthState`, hit `/api/integrations/jira/callback` with mocked `exchange_code_for_tokens` and `get_accessible_resources` → assert `JiraConnection` row created.
  2. `GET /api/integrations/jira/boards?connection_id=…` → assert non-empty result; second assertion with `get_boards` raising → confirm fallback to `get_projects` (not silent `[]`).
  3. `POST /api/integrations/jira/board-selection` → assert sync runs in-process (force Celery `.delay()` to raise to exercise the fallback path at `router.py:597-604`).
  4. `GET /api/integrations/jira/team-members?connection_id=…` → assert members present, issue counts populated.
  5. `POST /api/onboarding/confirm-team` → assert `onboarding_completed_at` set and `Developer` rows upserted.
  6. `POST /api/sprint-brain/plan` (JSON path, not SSE) → assert `200` with an `assignments` list. Stub `generate_sprint_plan` in `services/sprint_brain.py` to return a deterministic plan so the test doesn't hit Claude.
- Regression cases as parametrized variants: boards endpoint when agile API 401s; sync when Celery broker raises; team-members when Jira returns 502 (assert the route returns a structured error, not raw 502 — see Stream E).
- **Reuses:** `apps/api/tests/conftest.py:tmp_db`, `test_jira_router.py:_patch_clerk`, `test_track4_jira_push.py` AsyncMock idioms, `test_initiative_a_e2e.py` pipeline-stitching style.

---

### Stream B — Backend observability (Agent: `obs-backend`)

**Goal:** Replace "logs go to Railway stdout, hope for the best" with structured events, a sync-status table the frontend can poll, and Sentry alerts.

- **B1 — `SyncStatus` model + endpoint.**
  - New migration: `apps/api/alembic/versions/0026_sync_status.py` adding `sync_status` table: `team_id UUID PK FK`, `state TEXT` (`queued|running|complete|failed`), `started_at`, `finished_at`, `error_code TEXT NULL`, `error_message TEXT NULL`, `tickets_synced INT`, `members_synced INT`.
  - New model: `apps/api/src/models/sync_status.py`. Register in `apps/api/src/models/__init__.py`.
  - Write path: `sync_jira_team` (`apps/api/src/integrations/jira/sync.py:168-310`) and `_run_sync_in_process` (`router.py:43-61`) upsert `SyncStatus` rows at start, on success, and in the outermost `except`. Reuse the encryption-free DB session pattern already in `sync.py`.
  - New route: `GET /api/integrations/jira/sync-status/{team_id}` in `apps/api/src/integrations/jira/router.py`. Returns the row or `{state: "unknown"}` if missing. Auth: same Clerk + org membership check used by `/team-members`.
- **B2 — Structured `jira_sync_event` log emission.** Extend the `cost_tracker.py:143-154` pattern (`extra={"ai_cost": {...}}`) to emit `extra={"jira_sync": {"team_id": ..., "stage": ..., "duration_ms": ..., "ticket_count": ..., "status": ..., "error_code": ...}}` at each phase of `sync_jira_team`. Stages: `start`, `members_upserted`, `sprints_fetched`, `backlog_synced`, `complete`, `failed`.
- **B3 — Sentry SDK on FastAPI.** Add `sentry-sdk[fastapi]` to `apps/api/pyproject.toml`. Init in `apps/api/src/main.py` behind `SENTRY_DSN` env var (only when set — so local dev stays clean). Tag scope with `org_id` and `team_id` via FastAPI middleware. Document `SENTRY_DSN` in `DEPLOYMENT.md`.

---

### Stream C — Frontend (Agent: `frontend`) — depends on B

**Goal:** Frontend stops swallowing errors, polls sync status so `ConfirmTeam` is never stale, surfaces a Reset button, and is covered by one Playwright smoke. Sentry catches the regressions B doesn't.

- **C1 — Error surfacing.** Update `apps/web/src/components/JiraSyncControl.tsx:74-77` and `apps/web/src/pages/OnboardingPage.tsx` callsites to extract `error.response?.data?.detail` from `ApiError` and display it. Add a `<Toast>`/inline `<Alert>` for failures — reuse `apps/web/src/components/ui/Alert.tsx`. Add a single React `ErrorBoundary` around the onboarding route in `App.tsx`.
- **C2 — Poll `sync-status` from `ConfirmTeam`.** Replace the one-shot fetch at `OnboardingPage.tsx:640` with a TanStack Query that polls `GET /api/integrations/jira/sync-status/{team_id}` every 2s until `state === "complete"` or `"failed"`. While `running`, show the existing `ScanningScreen` spinner. On `complete`, refetch `/team-members`. On `failed`, show error + Reset button (C3).
- **C3 — Reset button.** Wire a "Reset connection / Restart import" button into `ConfirmTeam` and the `BoardPicker` failure state in `OnboardingPage.tsx`. Calls `POST /api/onboarding/reset` from Stream D, then `setStep(-1)` back to `WelcomeStep`. Confirmation modal before firing.
- **C4 — Sentry React.** Add `@sentry/react` to `apps/web/package.json`. Init in `apps/web/src/main.tsx` behind `VITE_SENTRY_DSN`. Wrap the existing TanStack Query client with the Sentry integration so query errors are captured.
- **C5 — Playwright smoke.** Brand-new Playwright setup (no existing config):
  - `apps/web/playwright.config.ts`, `apps/web/tests/e2e/onboarding.spec.ts`, devDependency `@playwright/test`.
  - One test: load `/onboarding` against `vite preview` with `VITE_API_URL` pointing at a pytest-launched backend (or a fixture-mode flag the API exposes that short-circuits Jira HTTP). The simplest path is the latter: add a `TEST_MODE=1` env var the API honors to return canned Jira responses without HTTP — keeps Playwright hermetic.
  - Steps: click "Connect Jira" (intercept the OAuth redirect, fake the callback by hitting the API directly), pick the first board, wait for `ScanningScreen` → `ConfirmTeam`, confirm, assert URL is `/app/sprint-planner`.

---

### Stream D — Reset endpoint (Agent: `reset-backend`)

**Goal:** The single backend route Stream C needs to unstick a user.

- New route in `apps/api/src/routers/onboarding.py`: `POST /api/onboarding/reset`. Auth: Clerk + org admin only.
- Behavior:
  - Deactivate all `JiraConnection` rows for the org (`is_active = False`).
  - Null `Team.jira_board_id`, `Team.jira_project_key`, `Team.onboarding_completed_at`.
  - Delete the team's `SyncStatus` row.
  - Leave `Developer` rows alone (preserves any user edits — re-running onboarding will upsert).
  - Return `{ok: true}`. All work in one transaction; on failure, log via the Stream B structured event and return `500` with `detail`.
- Add `test_onboarding_reset.py` test using the same `tmp_db` + `_patch_clerk` pattern.

---

### Stream E — Silent-failure surgery (Agent: `silent-failures`)

**Goal:** Replace bare `except: pass` and silent `[]` returns with structured logs from Stream B's logger.

- `apps/api/src/integrations/jira/sync.py:40-41` — event-loop fallback: keep behavior, but `logger.warning("event loop creation fallback", extra={...})`.
- `apps/api/src/integrations/jira/sync.py:155-156` and `:164-165` — date parsing: `logger.warning("date parse failed", extra={"jira_sync": {"team_id": ..., "field": ..., "raw_value": ...}})`. Behavior unchanged (return `None`), but failures become visible.
- `apps/api/src/integrations/jira/router.py:318-355` — boards endpoint: split error swallow into two branches: real auth/scope errors return `502` with structured `detail`, empty-state returns `[]`. Stream A's regression test enforces the boundary.
- `apps/api/src/integrations/jira/router.py:43-61` — `_run_sync_in_process` already logs via c1ed169; add the Stream B structured event so the failure also lands in `SyncStatus`.

---

### Stream F — CI (Agent: `ci`) — depends on A and C

**Goal:** Make the new tests gate `main`.

- New file: `.github/workflows/test.yml`.
- Jobs:
  - `backend`: Python 3.12, install `apps/api` with `pip install -e .[dev]`, run `pytest apps/api/tests` with `DATABASE_URL=sqlite+aiosqlite:///:memory:`.
  - `frontend`: Node 20, `pnpm install`, `pnpm --filter web exec playwright install --with-deps chromium`, `pnpm --filter web build`, then `pnpm --filter web exec playwright test`. Uses `TEST_MODE=1` API per Stream C5.
- Triggers: every PR into `main`, plus push to `main`. Required status check on the branch protection rule.
- Document the workflow in `DEPLOYMENT.md` under a new "CI" section.

---

## Critical files

| Stream | File | Action |
| --- | --- | --- |
| A | `apps/api/tests/test_onboarding_flow_e2e.py` | new |
| B | `apps/api/alembic/versions/0026_sync_status.py` | new |
| B | `apps/api/src/models/sync_status.py` | new |
| B | `apps/api/src/models/__init__.py` | register model |
| B | `apps/api/src/integrations/jira/sync.py` | write `SyncStatus`; emit structured events |
| B | `apps/api/src/integrations/jira/router.py:43-61`, `:548-606` | write `SyncStatus` from in-process + Celery paths; new `GET /sync-status/{team_id}` |
| B | `apps/api/src/main.py`, `apps/api/pyproject.toml` | Sentry init + dep |
| B | `DEPLOYMENT.md` | document `SENTRY_DSN` |
| C | `apps/web/src/components/JiraSyncControl.tsx:74-77` | surface `detail` |
| C | `apps/web/src/pages/OnboardingPage.tsx:640`, `:1080-1195` | poll `sync-status`; wire Reset button |
| C | `apps/web/src/App.tsx` | `ErrorBoundary` around onboarding route |
| C | `apps/web/src/main.tsx`, `apps/web/package.json` | Sentry React init + dep |
| C | `apps/web/playwright.config.ts`, `apps/web/tests/e2e/onboarding.spec.ts` | new |
| D | `apps/api/src/routers/onboarding.py` | new `POST /reset` |
| D | `apps/api/tests/test_onboarding_reset.py` | new |
| E | `apps/api/src/integrations/jira/sync.py:40-41`, `:155-156`, `:164-165` | replace bare `except: pass` with `logger.warning` |
| E | `apps/api/src/integrations/jira/router.py:318-355` | distinguish auth errors from empty state |
| F | `.github/workflows/test.yml` | new |

## Reuse — do not reinvent

- `apps/api/tests/conftest.py` → `tmp_db` async fixture.
- `apps/api/tests/test_jira_router.py` → `_patch_clerk()` helper, `JiraConnection` seeding pattern.
- `apps/api/tests/test_track4_jira_push.py` → `AsyncMock(httpx.AsyncClient)` stubbing.
- `apps/api/src/services/cost_tracker.py:143-154` → `logger.info(..., extra={"jira_sync": {...}})` structured-event pattern.
- `apps/web/src/components/ui/Alert.tsx` → existing error display component (no new toast library).
- `apps/web/src/lib/api.ts`'s `ApiError` type → already carries `response.data.detail`.

## Verification

End-to-end proof, not just unit greens:

1. `pytest apps/api/tests/test_onboarding_flow_e2e.py -v` — happy path + each parametrized regression variant green.
2. `pytest apps/api/tests/test_onboarding_reset.py -v` — reset green.
3. `pytest apps/api/tests -v` — full suite passes (no regressions in the existing 25+ tests).
4. Manual: `pnpm dev` locally, walk through onboarding with `TEST_MODE=1` API → confirm `ConfirmTeam` waits for `sync-status` to flip to `complete`, error toasts appear when sync fails, Reset returns to `WelcomeStep`.
5. `pnpm --filter web exec playwright test` — Playwright onboarding spec green locally.
6. Push a throwaway branch, open PR → confirm GitHub Actions `backend` + `frontend` jobs both run and are required.
7. Trigger a real sync failure in local dev (e.g., set `JIRA_CLIENT_SECRET` to garbage) → confirm Sentry event arrives in the project; `SyncStatus` row shows `failed` with `error_message` populated; frontend displays `error.detail`.
8. Hit `POST /api/onboarding/reset` against a fully-onboarded local org → confirm subsequent page load returns to onboarding entry, `Developer` rows still present.

## Out of scope (intentional)

- Multi-board / switch-board support (already deferred to post-beta in `tasks/todo.md:97`).
- Stripe billing configuration (separate checklist in `tasks/todo.md:61-89`).
- Replacing the omada-simulator's live-Jira approach — keep as-is for post-beta validation.
- Performance work on `/plan` SSE — covered by `Initiative C — Sprint Gen Speed` Phase 1, already shipped.
- Frontend unit tests beyond the single Playwright smoke — not the leverage point for beta.
- Backfilling structured logs across non-Jira routes — Stream B's pattern can be extended later.
