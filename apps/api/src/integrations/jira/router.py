"""
Jira integration routes.

GET  /api/integrations/jira/connect   → returns Atlassian OAuth2 authorization URL
GET  /api/integrations/jira/callback  → handles OAuth2 code exchange, saves connection
GET  /api/integrations/jira/status    → returns connection status for the current org
DELETE /api/integrations/jira/disconnect → deactivates the connection
POST /api/integrations/jira/sync      → triggers a manual background sync for a team
"""

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.config import settings
from src.database import get_db
from src.integrations.jira.oauth import (
    exchange_code_for_tokens,
    get_accessible_resources,
    get_authorization_url,
)
from src.models.jira_connection import JiraConnection
from src.services.encryption import decrypt, encrypt

router = APIRouter(prefix="/api/integrations/jira", tags=["jira"])

# In-process state store — keyed by (state_token -> user_id).
# Replace with Redis in production for multi-instance deployments.
_oauth_states: dict[str, str] = {}


@router.get("/connect")
async def jira_connect(user_id: str = Depends(get_current_user_id)):
    """
    Return the Atlassian OAuth2 authorization URL.
    The frontend redirects the user to this URL to begin the OAuth flow.
    """
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = user_id
    return {"auth_url": get_authorization_url(state)}


@router.get("/callback")
async def jira_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Atlassian redirects here after the user grants access.
    Exchanges the code for tokens and persists the JiraConnection.
    """
    user_id = _oauth_states.pop(state, None)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    tokens = await exchange_code_for_tokens(code)
    resources = await get_accessible_resources(tokens["access_token"])

    if not resources:
        raise HTTPException(status_code=400, detail="No accessible Jira sites found")

    # For MVP take the first site; multi-site selection can be added later.
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
        # organization_id resolved by coordinator once org service exists;
        # placeholder uses a nil UUID so the row is created and FK updated later.
        organization_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        jira_cloud_id=resource["id"],
        jira_cloud_url=resource["url"],
        encrypted_access_token=encrypt(tokens["access_token"]),
        encrypted_refresh_token=encrypt(tokens.get("refresh_token", "")),
        token_expires_at=expires_at,
        scopes=tokens.get("scope", "").split(),
    )
    db.add(connection)
    await db.flush()

    return RedirectResponse(
        f"{settings.frontend_url}/onboarding/jira-connected?connection_id={connection.id}"
    )


@router.get("/status")
async def jira_status(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Return whether the current org has an active Jira connection.
    Full org-scoping is wired up once the org service exists.
    """
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.is_active == True).limit(1)
    )
    connection = result.scalar_one_or_none()
    if not connection:
        return {"connected": False}
    return {
        "connected": True,
        "cloud_url": connection.jira_cloud_url,
        "last_synced_at": connection.last_synced_at.isoformat() if connection.last_synced_at else None,
    }


@router.delete("/disconnect")
async def jira_disconnect(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the org's Jira connection."""
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.is_active == True)
    )
    connections = result.scalars().all()
    if not connections:
        raise HTTPException(status_code=404, detail="No active Jira connection found")
    for conn in connections:
        conn.is_active = False
    return {"disconnected": True}


@router.post("/sync")
async def trigger_sync(
    team_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Enqueue a background Celery task to sync a team's Jira data.
    Returns the task ID so the client can poll for status.
    """
    from src.integrations.jira.sync import sync_jira_team

    task = sync_jira_team.delay(team_id)
    return {"task_id": task.id, "status": "queued"}
