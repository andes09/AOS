# Jira OAuth Integration Fix — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Jira OAuth integration so the full onboarding flow works end-to-end: connect Jira → select scrum board → sync data, with a settings page for managing the connection post-onboarding.

**Architecture:** Backend-callback OAuth flow. Atlassian redirects to the FastAPI backend which exchanges the code, saves the `JiraConnection` with the real `organization_id` (resolved from the state token), then redirects the browser to the frontend with `?connection_id=`. The frontend detects this param and advances through onboarding. A Celery beat schedule handles periodic syncs.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), React + `useApi` hook (frontend), Celery + Redis (sync schedule)

**Spec:** `docs/superpowers/specs/2026-03-18-jira-oauth-design.md`

---

## Chunk 1: Backend — Router, Org Wiring, New Endpoints, Migration

### Task 1: Fix router.py — register, org_id state store, org-scoped status/disconnect

**Files:**
- Modify: `apps/api/src/main.py`
- Modify: `apps/api/src/integrations/jira/router.py`

- [ ] **Step 1: Write failing tests for /connect and /callback org wiring**

Add to `apps/api/tests/test_jira_router.py` (create file):

```python
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from src.main import app


def _patch_clerk(user_id="user_1", org_id="org_abc"):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _patch_no_org(user_id="user_1"):
    payload = {"sub": user_id}  # no org_id
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


@pytest.mark.asyncio
async def test_jira_connect_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/integrations/jira/connect")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_jira_connect_requires_org_context():
    with _patch_no_org():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/jira/connect",
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_jira_connect_returns_auth_url():
    with _patch_clerk():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/jira/connect",
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert "auth_url" in body
    assert "auth.atlassian.com" in body["auth_url"]


@pytest.mark.asyncio
async def test_jira_callback_invalid_state():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/integrations/jira/callback",
            params={"code": "abc123", "state": "nonexistent_state"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_jira_callback_stores_real_org_id(tmp_db):
    """Callback resolves org_id from state and saves JiraConnection with real organization_id."""
    from src.integrations.jira import router as jira_router
    import uuid

    # Pre-seed an org and the state entry
    org_clerk_id = "org_test_123"
    fake_state = "test_state_token"
    jira_router._oauth_states[fake_state] = {"user_id": "user_1", "org_id": org_clerk_id}

    # Pre-seed the org in DB (use the tmp_db fixture which sets up the DB)
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from src.database import get_db
    from src.models.organization import Organization

    # Insert org directly — tmp_db fixture has already overridden get_db
    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=org_clerk_id,
            name="Test Org",
            slug=org_clerk_id,
            use_managed_key=False,
        )
        db.add(org)
        await db.commit()
        org_id = org.id
        break

    mock_tokens = {
        "access_token": "at_test",
        "refresh_token": "rt_test",
        "expires_in": 3600,
        "scope": "read:jira-work",
    }
    mock_resources = [{"id": "cloud_abc", "url": "https://mysite.atlassian.net"}]

    with (
        patch("src.integrations.jira.router.exchange_code_for_tokens", new=AsyncMock(return_value=mock_tokens)),
        patch("src.integrations.jira.router.get_accessible_resources", new=AsyncMock(return_value=mock_resources)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            resp = await client.get(
                "/api/integrations/jira/callback",
                params={"code": "auth_code", "state": fake_state},
            )

    # Should redirect to frontend
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "connection_id=" in location

    # Verify JiraConnection was saved with real org_id
    from src.models.jira_connection import JiraConnection
    from sqlalchemy import select
    async for db in app.dependency_overrides[get_db]():
        conn = await db.scalar(select(JiraConnection).where(JiraConnection.organization_id == org_id))
        assert conn is not None
        assert str(conn.organization_id) != "00000000-0000-0000-0000-000000000000"
        break
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd apps/api && pytest tests/test_jira_router.py -v
```

Expected: `ImportError` or `404` (router not mounted, endpoints don't match).

- [ ] **Step 3: Register the Jira router in main.py**

In `apps/api/src/main.py`, add after the existing router imports:

```python
from src.integrations.jira import router as jira_router
```

And add after the existing `app.include_router(...)` calls:

```python
app.include_router(jira_router.router)
```

- [ ] **Step 4: Rewrite router.py with org_id state store and org-scoped endpoints**

Replace the full contents of `apps/api/src/integrations/jira/router.py`:

```python
"""
Jira integration routes.

GET    /api/integrations/jira/connect       → returns Atlassian OAuth2 authorization URL
GET    /api/integrations/jira/callback      → handles OAuth2 code exchange, saves connection
GET    /api/integrations/jira/status        → returns connection status for the current org
DELETE /api/integrations/jira/disconnect    → deactivates the connection
GET    /api/integrations/jira/boards        → lists scrum boards for a connection
POST   /api/integrations/jira/board-selection → saves the selected board to the team
POST   /api/integrations/jira/sync          → triggers a manual background sync for a team
"""

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id, get_current_org_id
from src.config import settings
from src.database import get_db
from src.integrations.jira.client import JiraClient
from src.integrations.jira.oauth import (
    exchange_code_for_tokens,
    get_accessible_resources,
    get_authorization_url,
    refresh_access_token,
)
from src.models.jira_connection import JiraConnection
from src.models.organization import Organization
from src.models.team import Team
from src.services.encryption import decrypt, encrypt

router = APIRouter(prefix="/api/integrations/jira", tags=["jira"])

# In-process state store: state_token → {user_id, org_id}
# Replace with Redis in production for multi-instance deployments.
_oauth_states: dict[str, dict] = {}


@router.get("/connect")
async def jira_connect(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
):
    """Return the Atlassian OAuth2 authorization URL."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"user_id": user_id, "org_id": clerk_org_id}
    return {"auth_url": get_authorization_url(state)}


@router.get("/callback")
async def jira_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Atlassian redirects here after the user grants access.
    Exchanges the code for tokens, resolves the real org_id from the state
    token, and persists the JiraConnection.
    """
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    clerk_org_id = state_data["org_id"]

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(
            status_code=400,
            detail="Organisation not found — complete onboarding first",
        )

    tokens = await exchange_code_for_tokens(code)
    resources = await get_accessible_resources(tokens["access_token"])

    if not resources:
        raise HTTPException(status_code=400, detail="No accessible Jira sites found")

    resource = resources[0]

    expires_at = None
    if "expires_in" in tokens:
        expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])

    # Deactivate any existing connection for this cloud site (re-auth case)
    existing = await db.execute(
        select(JiraConnection).where(
            JiraConnection.jira_cloud_id == resource["id"],
            JiraConnection.is_active == True,
        )
    )
    for conn in existing.scalars().all():
        conn.is_active = False

    connection = JiraConnection(
        organization_id=org.id,
        jira_cloud_id=resource["id"],
        jira_cloud_url=resource["url"],
        encrypted_access_token=encrypt(tokens["access_token"]),
        encrypted_refresh_token=encrypt(tokens.get("refresh_token", "")),
        token_expires_at=expires_at,
        scopes=tokens.get("scope", "").split(),
    )
    db.add(connection)
    await db.flush()
    await db.commit()

    return RedirectResponse(
        f"{settings.frontend_url}/onboarding?connection_id={connection.id}"
    )


@router.get("/status")
async def jira_status(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return whether the current org has an active Jira connection."""
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        return {"connected": False}

    connection = await db.scalar(
        select(JiraConnection).where(
            JiraConnection.organization_id == org.id,
            JiraConnection.is_active == True,
        )
    )
    if not connection:
        return {"connected": False}
    return {
        "connected": True,
        "cloud_url": connection.jira_cloud_url,
        "last_synced_at": connection.last_synced_at.isoformat() if connection.last_synced_at else None,
    }


@router.delete("/disconnect")
async def jira_disconnect(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the org's Jira connection."""
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    result = await db.execute(
        select(JiraConnection).where(
            JiraConnection.organization_id == org.id,
            JiraConnection.is_active == True,
        )
    )
    connections = result.scalars().all()
    if not connections:
        raise HTTPException(status_code=404, detail="No active Jira connection found")
    for conn in connections:
        conn.is_active = False
    await db.commit()
    return {"disconnected": True}


@router.get("/boards")
async def get_jira_boards(
    connection_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List scrum boards for a Jira connection."""
    try:
        conn_uuid = uuid.UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id")

    connection = await db.get(JiraConnection, conn_uuid)
    if not connection or not connection.is_active:
        raise HTTPException(status_code=404, detail="Jira connection not found")

    access_token = decrypt(connection.encrypted_access_token)

    if connection.token_expires_at and connection.token_expires_at <= datetime.utcnow():
        refresh_tok = decrypt(connection.encrypted_refresh_token)
        tokens = await refresh_access_token(refresh_tok)
        access_token = tokens["access_token"]
        connection.encrypted_access_token = encrypt(access_token)
        if "refresh_token" in tokens:
            connection.encrypted_refresh_token = encrypt(tokens["refresh_token"])
        if "expires_in" in tokens:
            connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        await db.commit()

    client = JiraClient(cloud_id=connection.jira_cloud_id, access_token=access_token)
    boards = await client.get_boards()

    return [
        {
            "id": str(b["id"]),
            "name": b["name"],
            "project_key": b.get("location", {}).get("projectKey", ""),
        }
        for b in boards
        if b.get("type") == "scrum"
    ]


class BoardSelectionRequest(BaseModel):
    connection_id: str
    board_id: str
    project_key: str


@router.post("/board-selection")
async def save_board_selection(
    body: BoardSelectionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Save the selected scrum board to the team and trigger initial sync."""
    try:
        conn_uuid = uuid.UUID(body.connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id")

    connection = await db.get(JiraConnection, conn_uuid)
    if not connection or not connection.is_active:
        raise HTTPException(status_code=404, detail="Jira connection not found")

    team = await db.scalar(
        select(Team).where(Team.organization_id == connection.organization_id)
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found for this organisation")

    team.jira_board_id = body.board_id
    team.jira_project_key = body.project_key
    await db.commit()

    from src.integrations.jira.sync import sync_jira_team
    sync_jira_team.delay(str(team.id))

    return {"saved": True}


@router.post("/sync")
async def trigger_sync(
    team_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Enqueue a background Celery task to sync a team's Jira data."""
    from src.integrations.jira.sync import sync_jira_team
    task = sync_jira_team.delay(team_id)
    return {"task_id": task.id, "status": "queued"}
```

- [ ] **Step 5: Run tests — expect connect and callback tests to pass**

```bash
cd apps/api && pytest tests/test_jira_router.py::test_jira_connect_requires_auth tests/test_jira_router.py::test_jira_connect_requires_org_context tests/test_jira_router.py::test_jira_connect_returns_auth_url tests/test_jira_router.py::test_jira_callback_invalid_state -v
```

Expected: 4 × PASSED

- [ ] **Step 6: Run callback org_id test**

```bash
cd apps/api && pytest tests/test_jira_router.py::test_jira_callback_stores_real_org_id -v
```

Expected: PASSED

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/main.py apps/api/src/integrations/jira/router.py apps/api/tests/test_jira_router.py
git commit -m "feat: register Jira router, fix org_id wiring, add boards and board-selection endpoints"
```

---

### Task 2: Add jira_project_key to Team model + migration

**Files:**
- Modify: `apps/api/src/models/team.py`
- Create: `apps/api/alembic/versions/0002_add_team_jira_project_key.py`

- [ ] **Step 1: Add jira_project_key to the Team model**

In `apps/api/src/models/team.py`, add after the `jira_board_id` line:

```python
jira_project_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
```

- [ ] **Step 2: Create the migration**

Create `apps/api/alembic/versions/0002_add_team_jira_project_key.py`:

```python
"""add jira_project_key to teams

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('teams', sa.Column('jira_project_key', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('teams', 'jira_project_key')
```

- [ ] **Step 3: Run the migration**

```bash
cd apps/api && alembic upgrade head
```

Expected: `Running upgrade 0001 -> 0002, add jira_project_key to teams`

- [ ] **Step 4: Run board-selection test**

Add this test to `apps/api/tests/test_jira_router.py`:

```python
@pytest.mark.asyncio
async def test_board_selection_saves_to_team(tmp_db):
    """POST /board-selection saves board_id and project_key to the team."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.database import get_db
    from sqlalchemy import select
    import uuid

    org_id = uuid.uuid4()
    team_id = uuid.uuid4()
    conn_id = uuid.uuid4()

    async for db in app.dependency_overrides[get_db]():
        org = Organization(id=org_id, clerk_org_id="org_bs", name="BS Org", slug="org_bs", use_managed_key=False)
        team = Team(id=team_id, organization_id=org_id, name="BS Team", sprint_length_days=14)
        conn = JiraConnection(
            id=conn_id,
            organization_id=org_id,
            jira_cloud_id="cloud_bs",
            jira_cloud_url="https://bs.atlassian.net",
            encrypted_access_token="enc_at",
            encrypted_refresh_token="enc_rt",
            is_active=True,
        )
        db.add_all([org, team, conn])
        await db.commit()
        break

    with _patch_clerk():
        # Patch at the import site in router.py, not in sync.py, because the router
        # imports sync_jira_team lazily inside the function body.
        with patch("src.integrations.jira.sync.sync_jira_team") as mock_task:
            mock_task.delay = MagicMock()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/integrations/jira/board-selection",
                    json={"connection_id": str(conn_id), "board_id": "42", "project_key": "PROJ"},
                    headers={"Authorization": "Bearer tok"},
                )
    assert resp.status_code == 200
    assert resp.json()["saved"] is True

    async for db in app.dependency_overrides[get_db]():
        team = await db.get(Team, team_id)
        assert team.jira_board_id == "42"
        assert team.jira_project_key == "PROJ"
        break
```

```bash
cd apps/api && pytest tests/test_jira_router.py::test_board_selection_saves_to_team -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/models/team.py apps/api/alembic/versions/0002_add_team_jira_project_key.py apps/api/tests/test_jira_router.py
git commit -m "feat: add jira_project_key to Team model and migration"
```

---

## Chunk 2: Frontend — Onboarding Flow Fix

### Task 3: Fix ConnectJiraStep and thread connection_id through OnboardingPage

**Files:**
- Modify: `apps/web/src/pages/onboarding/ConnectJiraStep.tsx`
- Modify: `apps/web/src/pages/OnboardingPage.tsx`

- [ ] **Step 1: Rewrite ConnectJiraStep.tsx**

Replace the full contents of `apps/web/src/pages/onboarding/ConnectJiraStep.tsx`:

```tsx
// apps/web/src/pages/onboarding/ConnectJiraStep.tsx

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../../lib/api'

interface ConnectJiraStepProps {
  onNext: (connectionId: string) => void
}

export function ConnectJiraStep({ onNext }: ConnectJiraStepProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const { get } = useApi()

  // Backend redirects back here with ?connection_id= after successful OAuth.
  useEffect(() => {
    const connectionId = searchParams.get('connection_id')
    if (connectionId) {
      setSearchParams({}, { replace: true }) // strip param from URL
      onNext(connectionId)
    }
  }, [])

  async function handleConnect() {
    setStatus('loading')
    setError(null)
    try {
      const data = await get<{ auth_url: string }>('/api/integrations/jira/connect')
      window.location.href = data.auth_url
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : 'Failed to initiate Jira connection')
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Connect Jira
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Connect your Atlassian account so Sprint Brain can read your team's tickets and sprint history.
      </p>

      {error && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{error}</div>
      )}
      <button
        onClick={handleConnect}
        disabled={status === 'loading'}
        style={primaryButtonStyle(status === 'loading' ? '#374151' : '#6366f1')}
      >
        {status === 'loading' ? 'Redirecting...' : 'Connect Atlassian Account →'}
      </button>
    </div>
  )
}

function primaryButtonStyle(bg: string): React.CSSProperties {
  return {
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '0.625rem 1.25rem',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    width: '100%',
  }
}
```

- [ ] **Step 2: Update OnboardingPage.tsx to thread connection_id**

Replace the full contents of `apps/web/src/pages/OnboardingPage.tsx`:

```tsx
// apps/web/src/pages/OnboardingPage.tsx

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { OnboardingLayout } from '../layouts/OnboardingLayout'
import { ConnectJiraStep } from './onboarding/ConnectJiraStep'
import { SelectBoardStep } from './onboarding/SelectBoardStep'
import { SaveAnthropicKeyStep } from './onboarding/SaveAnthropicKeyStep'

const STEPS = ['Connect Jira', 'Select Board', 'Anthropic Key'] as const
const STORAGE_KEY = 'aos_onboarding_step'

export function OnboardingPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<number>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? parseInt(saved, 10) : 0
  })
  const [connectionId, setConnectionId] = useState<string | null>(null)

  function goTo(next: number) {
    localStorage.setItem(STORAGE_KEY, String(next))
    setStep(next)
  }

  function advance(data?: string) {
    if (typeof data === 'string') {
      setConnectionId(data)
    }
    if (step === STEPS.length - 1) {
      localStorage.removeItem(STORAGE_KEY)
      navigate('/app/sprint-planner')
    } else {
      goTo(step + 1)
    }
  }

  function back() {
    goTo(step - 1)
  }

  return (
    <OnboardingLayout>
      {/* Step indicator */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2rem' }}>
        {STEPS.map((label, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: i < step ? '#6366f1' : 'transparent',
                border: i === step ? '2px solid #6366f1' : i < step ? 'none' : '2px solid #2d2f45',
                color: i < step ? '#fff' : i === step ? '#6366f1' : '#64748b',
                fontSize: 11,
                fontWeight: 700,
                flexShrink: 0,
              }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: 12, color: i === step ? '#e2e8f0' : '#64748b', whiteSpace: 'nowrap' }}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div style={{ width: 24, height: 1, background: '#2d2f45', margin: '0 8px', flexShrink: 0 }} />
            )}
          </div>
        ))}
      </div>

      {step === 0 && <ConnectJiraStep onNext={advance} />}
      {step === 1 && <SelectBoardStep connectionId={connectionId ?? ''} onNext={advance} onBack={back} />}
      {step === 2 && <SaveAnthropicKeyStep onNext={advance} onBack={back} />}
    </OnboardingLayout>
  )
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: no errors related to `ConnectJiraStep` or `OnboardingPage`.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/pages/onboarding/ConnectJiraStep.tsx apps/web/src/pages/OnboardingPage.tsx
git commit -m "feat: fix ConnectJiraStep OAuth flow and thread connection_id through OnboardingPage"
```

---

### Task 4: Fix SelectBoardStep to use correct endpoints

**Files:**
- Modify: `apps/web/src/pages/onboarding/SelectBoardStep.tsx`

- [ ] **Step 1: Update SelectBoardStep.tsx**

Replace the full contents of `apps/web/src/pages/onboarding/SelectBoardStep.tsx`:

```tsx
// apps/web/src/pages/onboarding/SelectBoardStep.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../lib/api'
import type { JiraBoard } from '../../types/sprint'

interface SelectBoardStepProps {
  connectionId: string
  onNext: () => void
  onBack: () => void
}

export function SelectBoardStep({ connectionId, onNext, onBack }: SelectBoardStepProps) {
  const [selectedBoardId, setSelectedBoardId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const { get, post } = useApi()

  const { data: boards, isLoading, error: fetchError, refetch } = useQuery({
    queryKey: ['jira-boards', connectionId],
    queryFn: () => get<JiraBoard[]>(`/api/integrations/jira/boards?connection_id=${connectionId}`),
    enabled: !!connectionId,
  })

  async function handleSave() {
    if (!selectedBoardId || !boards) return
    const board = boards.find(b => b.id === selectedBoardId)
    if (!board) return
    setSaving(true)
    setSaveError(null)
    try {
      await post('/api/integrations/jira/board-selection', {
        connection_id: connectionId,
        board_id: board.id,
        project_key: board.project_key,
      })
      onNext()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save board selection')
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Select Board
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Choose the Jira board Sprint Brain will use for sprint planning.
      </p>

      {isLoading && (
        <div style={{ color: '#64748b', fontSize: 14, marginBottom: '1.5rem' }}>Loading boards...</div>
      )}
      {fetchError && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>
            Failed to load boards. Check your Jira connection.
          </div>
          <button onClick={() => refetch()} style={ghostButtonStyle}>Retry</button>
        </div>
      )}
      {saveError && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{saveError}</div>
      )}

      {boards && (
        <div style={{ marginBottom: '1.5rem' }}>
          {boards.length === 0 ? (
            <div style={{ color: '#64748b', fontSize: 14 }}>
              No scrum boards found. Make sure your Jira account has access to at least one scrum project.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {boards.map(board => (
                <div
                  key={board.id}
                  onClick={() => setSelectedBoardId(board.id)}
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: 6,
                    border: `2px solid ${selectedBoardId === board.id ? '#6366f1' : '#2d2f45'}`,
                    background: selectedBoardId === board.id ? '#2d2f45' : 'transparent',
                    cursor: 'pointer',
                    transition: 'border-color 0.15s, background 0.15s',
                  }}
                >
                  <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 600 }}>{board.name}</div>
                  <div style={{ color: '#64748b', fontSize: 12, marginTop: 2 }}>{board.project_key}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onBack} style={ghostButtonStyle}>← Back</button>
        <button
          onClick={handleSave}
          disabled={!selectedBoardId || saving}
          style={primaryButtonStyle(!selectedBoardId || saving ? '#374151' : '#6366f1')}
        >
          {saving ? 'Saving...' : 'Continue →'}
        </button>
      </div>
    </div>
  )
}

const ghostButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: '#94a3b8',
  border: '1px solid #2d2f45',
  borderRadius: 6,
  padding: '0.625rem 1rem',
  fontSize: 14,
  cursor: 'pointer',
}

function primaryButtonStyle(bg: string): React.CSSProperties {
  return {
    flex: 1,
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '0.625rem 1.25rem',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/onboarding/SelectBoardStep.tsx
git commit -m "feat: fix SelectBoardStep to use correct Jira endpoints and accept connectionId prop"
```

---

## Chunk 3: Settings Page

### Task 5: Implement Jira connection card in SettingsPage

**Files:**
- Modify: `apps/web/src/pages/SettingsPage.tsx`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Add delete method to useApi**

In `apps/web/src/lib/api.ts`, add `del` to the returned object:

```typescript
del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
```

The full returned object should now be:
```typescript
return {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
```

- [ ] **Step 2: Implement SettingsPage.tsx**

Replace the full contents of `apps/web/src/pages/SettingsPage.tsx`:

```tsx
import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../lib/api'

interface JiraStatus {
  connected: boolean
  cloud_url?: string
  last_synced_at?: string | null
}

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<JiraStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const { get, del } = useApi()

  async function fetchStatus() {
    try {
      const data = await get<JiraStatus>('/api/integrations/jira/status')
      setStatus(data)
    } catch {
      setStatus({ connected: false })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    // If we just returned from an OAuth flow, strip the connection_id param
    if (searchParams.get('connection_id')) {
      setSearchParams({}, { replace: true })
    }
  }, [])

  async function handleDisconnect() {
    setActionLoading(true)
    setActionError(null)
    try {
      await del('/api/integrations/jira/disconnect')
      await fetchStatus()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to disconnect')
    } finally {
      setActionLoading(false)
    }
  }

  async function handleConnect() {
    setActionLoading(true)
    setActionError(null)
    try {
      const data = await get<{ auth_url: string }>('/api/integrations/jira/connect')
      window.location.href = data.auth_url
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to initiate connection')
      setActionLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <h1 style={{ color: '#e2e8f0', fontSize: '1.5rem', fontWeight: 700, marginBottom: '2rem' }}>
        Settings
      </h1>

      {/* Jira Connection Card */}
      <div style={{
        background: '#1e2030',
        border: '1px solid #2d2f45',
        borderRadius: 8,
        padding: '1.25rem 1.5rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <h2 style={{ color: '#e2e8f0', fontSize: '1rem', fontWeight: 600, margin: 0 }}>
            Jira Connection
          </h2>
          {!loading && status && (
            <span style={{
              fontSize: 12,
              fontWeight: 600,
              padding: '2px 10px',
              borderRadius: 999,
              background: status.connected ? '#14532d' : '#1e293b',
              color: status.connected ? '#4ade80' : '#64748b',
              border: `1px solid ${status.connected ? '#166534' : '#2d2f45'}`,
            }}>
              {status.connected ? 'Connected' : 'Not connected'}
            </span>
          )}
        </div>

        {loading ? (
          <div style={{ color: '#64748b', fontSize: 14 }}>Loading...</div>
        ) : status?.connected ? (
          <div>
            <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 4 }}>
              {status.cloud_url}
            </div>
            <div style={{ color: '#64748b', fontSize: 12, marginBottom: '1rem' }}>
              Last synced:{' '}
              {status.last_synced_at
                ? new Date(status.last_synced_at).toLocaleString()
                : 'Never'}
            </div>
            {actionError && (
              <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{actionError}</div>
            )}
            <button
              onClick={handleDisconnect}
              disabled={actionLoading}
              style={{
                background: 'transparent',
                color: '#ef4444',
                border: '1px solid #ef4444',
                borderRadius: 6,
                padding: '0.5rem 1rem',
                fontSize: 13,
                fontWeight: 600,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
                opacity: actionLoading ? 0.6 : 1,
              }}
            >
              {actionLoading ? 'Disconnecting...' : 'Disconnect'}
            </button>
          </div>
        ) : (
          <div>
            <p style={{ color: '#64748b', fontSize: 13, marginBottom: '1rem', margin: '0 0 1rem' }}>
              Connect your Atlassian account to enable sprint syncing.
            </p>
            {actionError && (
              <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{actionError}</div>
            )}
            <button
              onClick={handleConnect}
              disabled={actionLoading}
              style={{
                background: actionLoading ? '#374151' : '#6366f1',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                padding: '0.5rem 1.25rem',
                fontSize: 13,
                fontWeight: 600,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
              }}
            >
              {actionLoading ? 'Redirecting...' : 'Connect Jira'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/pages/SettingsPage.tsx apps/web/src/lib/api.ts
git commit -m "feat: implement Jira connection settings page with status, disconnect, and reconnect"
```

---

## Chunk 4: Sync Schedule

### Task 6: Add sync_all_teams, incremental_sync_all_teams, and beat schedule

**Files:**
- Modify: `apps/api/src/integrations/jira/sync.py`
- Modify: `apps/api/src/worker.py`

- [ ] **Step 1: Write failing tests for the scheduler tasks**

Add to `apps/api/tests/test_jira_sync.py` (create file):

```python
import pytest
import uuid
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
import src.models  # noqa: F401 — register all models

TEST_DB_URL = "sqlite:///./test_sync.db"


def _make_sync_session():
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _cleanup(engine):
    Base.metadata.drop_all(engine)
    engine.dispose()
    import os
    try:
        os.remove("./test_sync.db")
    except FileNotFoundError:
        pass


def test_sync_all_teams_dispatches_per_team():
    """sync_all_teams dispatches sync_jira_team.delay for each team with a board configured."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.integrations.jira.sync import sync_all_teams

    db, engine = _make_sync_session()
    try:
        org_id = uuid.uuid4()
        team_id = uuid.uuid4()
        org = Organization(id=org_id, clerk_org_id="org_s1", name="S1", slug="s1", use_managed_key=False)
        team = Team(id=team_id, organization_id=org_id, name="T1", sprint_length_days=14, jira_board_id="10")
        conn = JiraConnection(
            id=uuid.uuid4(),
            organization_id=org_id,
            jira_cloud_id="c1",
            jira_cloud_url="https://s1.atlassian.net",
            encrypted_access_token="x",
            encrypted_refresh_token="x",
            is_active=True,
        )
        db.add_all([org, team, conn])
        db.commit()

        with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
            with patch("src.integrations.jira.sync.sync_jira_team") as mock_task:
                mock_task.delay = MagicMock()
                sync_all_teams()
                mock_task.delay.assert_called_once_with(str(team_id))
    finally:
        db.close()
        _cleanup(engine)


def test_sync_all_teams_skips_teams_without_board():
    """sync_all_teams does not dispatch for teams with no board configured."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.integrations.jira.sync import sync_all_teams

    db, engine = _make_sync_session()
    try:
        org_id = uuid.uuid4()
        org = Organization(id=org_id, clerk_org_id="org_s2", name="S2", slug="s2", use_managed_key=False)
        team = Team(id=uuid.uuid4(), organization_id=org_id, name="T2", sprint_length_days=14)  # no board
        conn = JiraConnection(
            id=uuid.uuid4(),
            organization_id=org_id,
            jira_cloud_id="c2",
            jira_cloud_url="https://s2.atlassian.net",
            encrypted_access_token="x",
            encrypted_refresh_token="x",
            is_active=True,
        )
        db.add_all([org, team, conn])
        db.commit()

        with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
            with patch("src.integrations.jira.sync.sync_jira_team") as mock_task:
                mock_task.delay = MagicMock()
                sync_all_teams()
                mock_task.delay.assert_not_called()
    finally:
        db.close()
        _cleanup(engine)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd apps/api && pytest tests/test_jira_sync.py -v
```

Expected: `ImportError` or `AttributeError` — `sync_all_teams` does not exist yet.

- [ ] **Step 3: Add the two scheduler tasks to sync.py**

Note: `select` is already imported at the top of `sync.py` — no re-import needed.

Append to the end of `apps/api/src/integrations/jira/sync.py`:

```python

@celery_app.task
def sync_all_teams():
    """Full sync for every org that has an active Jira connection and a configured board."""
    from src.models.jira_connection import JiraConnection
    from src.models.team import Team

    db = _get_sync_session()
    try:
        connections = db.execute(
            select(JiraConnection).where(JiraConnection.is_active == True)
        ).scalars().all()

        for conn in connections:
            teams = db.execute(
                select(Team).where(
                    Team.organization_id == conn.organization_id,
                    Team.jira_board_id.isnot(None),
                )
            ).scalars().all()
            for team in teams:
                sync_jira_team.delay(str(team.id))
    finally:
        db.close()


@celery_app.task
def incremental_sync_all_teams():
    """Incremental sync of the active sprint for every configured team."""
    from src.models.jira_connection import JiraConnection
    from src.models.team import Team
    from src.models.sprint import Sprint, SprintStatus

    db = _get_sync_session()
    try:
        connections = db.execute(
            select(JiraConnection).where(JiraConnection.is_active == True)
        ).scalars().all()

        for conn in connections:
            teams = db.execute(
                select(Team).where(
                    Team.organization_id == conn.organization_id,
                    Team.jira_board_id.isnot(None),
                )
            ).scalars().all()
            for team in teams:
                active_sprint = db.execute(
                    select(Sprint).where(
                        Sprint.team_id == team.id,
                        Sprint.status == SprintStatus.ACTIVE,
                    )
                ).scalar_one_or_none()
                if active_sprint and active_sprint.jira_sprint_id:
                    sync_jira_sprint.delay(str(team.id), active_sprint.jira_sprint_id)
    finally:
        db.close()
```

- [ ] **Step 4: Run tests — expect both to pass**

```bash
cd apps/api && pytest tests/test_jira_sync.py -v
```

Expected: 2 × PASSED

- [ ] **Step 5: Add beat schedule to worker.py**

Replace the full contents of `apps/api/src/worker.py`:

```python
from celery import Celery
from celery.schedules import crontab
from src.config import settings

celery_app = Celery(
    "agile-os",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.integrations.jira.sync"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.beat_schedule = {
    "full-jira-sync-daily": {
        "task": "src.integrations.jira.sync.sync_all_teams",
        "schedule": crontab(hour=2, minute=0),   # 2am UTC daily
    },
    "incremental-jira-sync": {
        "task": "src.integrations.jira.sync.incremental_sync_all_teams",
        "schedule": crontab(minute="*/15"),        # every 15 minutes
    },
}
```

- [ ] **Step 6: Verify the worker imports cleanly**

```bash
cd apps/api && python -c "from src.worker import celery_app; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/integrations/jira/sync.py apps/api/src/worker.py apps/api/tests/test_jira_sync.py
git commit -m "feat: add sync_all_teams and incremental_sync_all_teams with Celery beat schedule"
```

---

## Manual Verification

After all chunks are complete, verify the full flow end-to-end:

1. Start Postgres, Redis, and the API: `cd apps/api && uvicorn src.main:app --reload --port 8000`
2. Start the frontend: `pnpm dev:web`
3. Sign in with an org account. You should land on `/onboarding`.
4. Click "Connect Atlassian Account" — you should be redirected to Atlassian.
5. After granting access, Atlassian redirects to `localhost:8000/api/integrations/jira/callback`, which redirects to `localhost:5173/onboarding?connection_id=<uuid>`.
6. The page auto-advances to "Select Board" and fetches your boards.
7. Select a board and click Continue. Verify in psql: `SELECT jira_board_id, jira_project_key FROM teams;`
8. Navigate to `/app/settings`. Confirm the Jira connection card shows "Connected" with the cloud URL.
9. Click Disconnect. Verify the card switches to "Not connected".
10. Click Connect Jira from settings — confirms the reconnect flow works.
