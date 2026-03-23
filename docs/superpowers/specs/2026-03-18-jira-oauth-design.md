# Jira OAuth Integration Fix — Design Spec

**Date:** 2026-03-18
**Branch:** feat/onboarding
**Status:** Approved

---

## Problem

The Jira OAuth integration was built in two independent tracks without an agreed API contract. The result:

- Jira router never registered in `main.py` — no Jira endpoints exist
- Frontend calls wrong paths (`/api/jira/oauth/initiate`, `/api/jira/oauth/callback`) with wrong HTTP methods
- Frontend and backend use incompatible OAuth flow designs
- Two endpoints the frontend needs don't exist (`/boards`, `/board-selection`)
- `JiraConnection.organization_id` is stored as a nil UUID placeholder
- No sync schedule configured

---

## OAuth Flow (Backend-Callback)

Atlassian redirects to the **backend**, not the frontend. The backend handles the code exchange and redirects the browser to the frontend with a `connection_id`.

```
User clicks Connect
  → Frontend: GET /api/integrations/jira/connect (authenticated)
  → Backend: generates state token, stores {user_id, org_id}, returns {auth_url}
  → Frontend: window.location.href = auth_url
  → Atlassian: user grants access
  → Atlassian: GET /api/integrations/jira/callback?code=...&state=...
  → Backend: validates state, exchanges code, fetches resources, saves JiraConnection with real org_id
  → Backend: RedirectResponse → http://localhost:5173/onboarding?connection_id=<uuid>
  → Frontend: detects ?connection_id=, advances to SelectBoardStep
  → Frontend: GET /api/integrations/jira/boards?connection_id=<uuid>
  → User selects board
  → Frontend: POST /api/integrations/jira/board-selection {connection_id, board_id, project_key}
  → Backend: saves board_id + project_key to Team record
```

`JIRA_REDIRECT_URI` remains `http://localhost:8000/api/integrations/jira/callback` — no Atlassian app settings change needed.

---

## Backend Changes

### 1. Register the router (`main.py`)
Add `app.include_router(jira_router.router)`.

### 2. Fix org_id on JiraConnection (`router.py`)
Extend `_oauth_states` from `dict[str, str]` to `dict[str, dict]`:
- At `/connect`: store `{"user_id": user_id, "org_id": clerk_org_id}`. Add `get_current_org_id` to dependencies.
- At `/callback`: unpack both, look up `Organization` by `clerk_org_id`, write real `organization_id` to `JiraConnection`.

### 3. Add `GET /boards` (`router.py`)
- Query param: `connection_id`
- Load `JiraConnection`, decrypt access token (refresh if expired)
- Call Jira REST API: `GET /rest/agile/1.0/board?type=scrum`
- Return `[{id, name, project_key}]`

### 4. Add `POST /board-selection` (`router.py`)
- Body: `{connection_id, board_id, project_key}`
- Load `JiraConnection` → get `organization_id` → get `Team` for that org
- Save `board_id` and `project_key` to `Team`
- Requires new `board_id` (String) and `project_key` (String) columns on `Team` model + Alembic migration

### 5. No changes to
`oauth.py`, `client.py`, `sync.py`, `encryption.py`

---

## Frontend Onboarding Changes

### `ConnectJiraStep.tsx`
- Replace `GET /api/jira/oauth/initiate` → `GET /api/integrations/jira/connect`, read `auth_url`
- Remove `useEffect` watching `?code=`
- Add `useEffect` watching `?connection_id=`; when found, call `onNext(connectionId)` and strip param from URL

### `SelectBoardStep.tsx`
- Replace `GET /api/jira/boards` → `GET /api/integrations/jira/boards?connection_id=<id>`
- Replace `POST /api/jira/board-selection` → `POST /api/integrations/jira/board-selection`
- Accept `connection_id` as a prop

### `OnboardingPage.tsx`
- Thread `connection_id` state: `ConnectJiraStep` produces it, `SelectBoardStep` consumes it

---

## Settings Page (`SettingsPage.tsx`)

Single **Jira Connection** card:

- **Connected state:** green badge, Jira cloud URL, last synced timestamp, "Disconnect" button
  - Disconnect: `DELETE /api/integrations/jira/disconnect` → re-fetch status
- **Disconnected state:** grey badge, "Connect Jira" button
  - Connect: same OAuth flow as onboarding; on return with `?connection_id=`, re-fetch status
- Status loaded on mount via `GET /api/integrations/jira/status`; re-fetched after connect/disconnect

No other settings sections in scope.

---

## Sync Schedule

### New Celery tasks (`sync.py`)
```python
@celery_app.task
def sync_all_teams():
    # query all active JiraConnections, dispatch sync_jira_team per team

@celery_app.task
def incremental_sync_all_teams():
    # same, calls incremental_sync_jira_team per team
```

### Beat schedule (`worker.py`)
```python
beat_schedule = {
    "full-jira-sync-daily": {
        "task": "src.integrations.jira.sync.sync_all_teams",
        "schedule": crontab(hour=2, minute=0),   # 2am UTC
    },
    "incremental-jira-sync": {
        "task": "src.integrations.jira.sync.incremental_sync_all_teams",
        "schedule": crontab(minute="*/15"),        # every 15 min
    },
}
```

Post-connection: trigger `sync_jira_team.delay(team_id)` immediately after board selection.

---

## Error Handling

| Scenario | Backend | Frontend |
|---|---|---|
| OAuth state mismatch/expiry | 400 HTTPException | "Connection failed, please try again" + retry |
| No accessible Jira sites | 400 HTTPException | Surface error message |
| Token refresh failure during sync | Mark `is_active=False` | Dashboard banner: "Jira disconnected — reconnect in Settings" |
| Board fetch fails | 4xx/5xx | Error state in SelectBoardStep + retry button |
| Sync failure | Logged server-side | Silent — last synced timestamp tells the story |

---

## Out of Scope

- Multi-site Jira support (MVP takes first accessible resource)
- Board re-selection post-onboarding (settings page shows status only)
- Celery worker infrastructure setup (Redis assumed running)
- Anthropic key management in settings
