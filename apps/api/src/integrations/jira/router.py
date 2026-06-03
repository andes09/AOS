"""
Jira integration routes.

GET    /api/integrations/jira/connect       → returns Atlassian OAuth2 authorization URL
GET    /api/integrations/jira/callback      → handles OAuth2 code exchange, saves connection
GET    /api/integrations/jira/status        → returns connection status for the current org
DELETE /api/integrations/jira/disconnect    → deactivates the connection
GET    /api/integrations/jira/boards        → lists scrum boards for a connection
POST   /api/integrations/jira/board-selection → saves the selected board to the team
PUT    /api/integrations/jira/board         → switch the active board/project (no re-OAuth)
POST   /api/integrations/jira/sync          → triggers a manual background sync for a team
"""

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
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
from src.models.oauth_state import OAuthState
from src.models.organization import Organization
from src.models.team import Team
from src.services.encryption import decrypt, encrypt

router = APIRouter(prefix="/api/integrations/jira", tags=["jira"])


@router.get("/connect")
async def jira_connect(
    return_to: str = Query(default="/onboarding"),
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the Atlassian OAuth2 authorization URL."""
    state = secrets.token_urlsafe(32)
    db.add(OAuthState(
        state=state,
        user_id=user_id,
        org_id=clerk_org_id,
        return_to=return_to,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    ))
    await db.commit()
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
    try:
        await db.execute(delete(OAuthState).where(OAuthState.expires_at < datetime.utcnow()))
    except Exception:
        pass

    state_row = await db.scalar(select(OAuthState).where(OAuthState.state == state))
    if not state_row:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if state_row.expires_at < datetime.utcnow():
        await db.delete(state_row)
        await db.commit()
        raise HTTPException(status_code=400, detail="OAuth state expired — please try again")
    clerk_org_id = state_row.org_id
    return_to = state_row.return_to
    await db.delete(state_row)

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

    # Use the first resource returned — the user selects their site on the
    # Atlassian OAuth consent page before being redirected back here.
    resource = resources[0]

    expires_at = None
    if "expires_in" in tokens:
        expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])

    # Deactivate ALL existing active connections for this org, then create
    # a fresh one for the chosen site.
    existing = await db.execute(
        select(JiraConnection).where(
            JiraConnection.organization_id == org.id,
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
    await db.commit()

    frontend_base = settings.frontend_url.split(",")[0].strip()
    return RedirectResponse(f"{frontend_base}{return_to}?connection_id={connection.id}")


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
    clerk_org_id: str = Depends(get_current_org_id),
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

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org or connection.organization_id != org.id:
        raise HTTPException(status_code=403, detail="Access denied")

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
    try:
        boards = await client.get_boards()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("get_boards failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Jira API error: {exc}")

    return [
        {
            "id": str(b["id"]),
            "name": b["name"],
            "project_key": b.get("location", {}).get("projectKey", ""),
        }
        for b in boards
    ]


class BoardSelectionRequest(BaseModel):
    connection_id: str
    board_id: str
    project_key: str


@router.post("/board-selection")
async def save_board_selection(
    body: BoardSelectionRequest,
    clerk_org_id: str = Depends(get_current_org_id),
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

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org or connection.organization_id != org.id:
        raise HTTPException(status_code=403, detail="Access denied")

    team = await db.scalar(
        select(Team).where(Team.organization_id == connection.organization_id)
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found for this organisation")

    team.jira_board_id = body.board_id
    team.jira_project_key = body.project_key
    await db.commit()

    try:
        from src.integrations.jira.sync import sync_jira_team
        sync_jira_team.delay(str(team.id))
    except Exception:
        pass  # Celery/broker not available; sync will run on next scheduled beat

    return {"saved": True}


class BoardSwitchRequest(BaseModel):
    board_id: int
    project_key: str
    team_id: str | None = None


@router.put("/board")
async def switch_board(
    body: BoardSwitchRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Switch a team's active Jira board/project without re-OAuth.

    The connection credentials stay the same — only the board/project
    being synced changes. Used by the simulator after creating a fresh
    SIM project so the manual disconnect+reconnect flow can be skipped.
    Triggers an initial sync against the new board.

    If ``team_id`` is omitted, the org's primary team is updated
    (backward-compatible stage-1 behaviour). If ``team_id`` is provided,
    that specific team is targeted — but only if it belongs to the
    caller's current organisation (404 otherwise).
    """
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    connection = await db.scalar(
        select(JiraConnection).where(
            JiraConnection.organization_id == org.id,
            JiraConnection.is_active == True,
        )
    )
    if not connection:
        raise HTTPException(
            status_code=404,
            detail="No active Jira connection — connect via OAuth first",
        )

    if body.team_id is not None:
        try:
            target_team_id = uuid.UUID(body.team_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=404, detail="Team not found for this organisation")
        team = await db.scalar(
            select(Team).where(
                Team.id == target_team_id,
                Team.organization_id == org.id,
            )
        )
    else:
        team = await db.scalar(
            select(Team).where(Team.organization_id == org.id)
        )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found for this organisation")

    team.jira_board_id = str(body.board_id)
    team.jira_project_key = body.project_key
    await db.commit()

    try:
        from src.integrations.jira.sync import sync_jira_team
        sync_jira_team.delay(str(team.id))
    except Exception:
        pass  # Celery/broker not available; next scheduled beat will pick it up

    return {
        "team_id": str(team.id),
        "board_id": body.board_id,
        "project_key": body.project_key,
    }


@router.post("/sync")
async def trigger_sync(
    team_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Enqueue a background Celery task to sync a team's Jira data."""
    from src.integrations.jira.sync import sync_jira_team
    task = sync_jira_team.delay(team_id)
    return {"task_id": task.id, "status": "queued"}
