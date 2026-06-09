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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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

    expires_at = None
    if "expires_in" in tokens:
        expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])

    # Deactivate all existing active connections for this org.
    existing = await db.execute(
        select(JiraConnection).where(
            JiraConnection.organization_id == org.id,
            JiraConnection.is_active == True,
        )
    )
    for conn in existing.scalars().all():
        conn.is_active = False

    # Create one inactive connection per accessible resource. The frontend
    # will ask the user which site to use, then call /activate.
    connection_ids = []
    for resource in resources:
        connection = JiraConnection(
            organization_id=org.id,
            jira_cloud_id=resource["id"],
            jira_cloud_url=resource["url"],
            encrypted_access_token=encrypt(tokens["access_token"]),
            encrypted_refresh_token=encrypt(tokens.get("refresh_token", "")),
            token_expires_at=expires_at,
            scopes=tokens.get("scope", "").split(),
            is_active=False,
        )
        db.add(connection)
        await db.flush()
        connection_ids.append(f"{connection.id}|{resource['url']}")

    await db.commit()

    frontend_base = settings.frontend_url.split(",")[0].strip()
    if len(connection_ids) == 1:
        cid = connection_ids[0].split("|")[0]
        conn_obj = await db.get(JiraConnection, uuid.UUID(cid))
        conn_obj.is_active = True
        await db.commit()
        return RedirectResponse(f"{frontend_base}{return_to}?connection_id={cid}")

    encoded = ",".join(connection_ids)
    return RedirectResponse(f"{frontend_base}{return_to}?pending_sites={encoded}")


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
    connection_id: str = Query(default=None),
    connection_ids: str = Query(default=None),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List scrum boards.

    Accepts either ?connection_id=<uuid> (single active connection) or
    ?connection_ids=<uuid1>,<uuid2>,... (pending connections from multi-site
    OAuth). In the latter case boards from all connections are aggregated and
    each board carries a connection_id field so board-selection can activate
    the right connection transparently.
    """
    import asyncio as _asyncio
    import logging as _logging

    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=403, detail="Access denied")

    # Resolve the list of connections to query.
    if connection_ids:
        ids = [s.strip() for s in connection_ids.split(",") if s.strip()]
        result = await db.execute(
            select(JiraConnection).where(
                JiraConnection.id.in_([uuid.UUID(i) for i in ids]),
                JiraConnection.organization_id == org.id,
            )
        )
        connections = result.scalars().all()
    elif connection_id:
        try:
            conn_uuid = uuid.UUID(connection_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid connection_id")
        connection = await db.get(JiraConnection, conn_uuid)
        if not connection or connection.organization_id != org.id:
            raise HTTPException(status_code=404, detail="Jira connection not found")
        connections = [connection]
    else:
        raise HTTPException(status_code=400, detail="connection_id or connection_ids required")

    async def _boards_for_connection(conn: JiraConnection) -> list[dict]:
        access_token = decrypt(conn.encrypted_access_token)
        if conn.token_expires_at and conn.token_expires_at <= datetime.utcnow():
            try:
                refresh_tok = decrypt(conn.encrypted_refresh_token)
                tokens = await refresh_access_token(refresh_tok)
                access_token = tokens["access_token"]
                conn.encrypted_access_token = encrypt(access_token)
                if "refresh_token" in tokens:
                    conn.encrypted_refresh_token = encrypt(tokens["refresh_token"])
                if "expires_in" in tokens:
                    conn.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to refresh Jira token: {exc}",
                )
        client = JiraClient(cloud_id=conn.jira_cloud_id, access_token=access_token)
        raw = []
        agile_failed = False
        try:
            raw = await client.get_boards()
        except Exception as exc:
            body = getattr(exc, "response", None)
            status_code = getattr(body, "status_code", None) if body else None
            body_text = ""
            if body is not None:
                try:
                    body_text = body.text[:300]
                except Exception:
                    pass
            _logging.getLogger(__name__).warning(
                "get_boards failed for %s (status=%s): %s %s",
                conn.jira_cloud_url, status_code, exc, body_text,
            )
            # 403/404 = missing Agile scope or no Jira Software — fall back to
            # project list. Other errors (5xx, network) re-raise so the caller
            # sees the real failure.
            if status_code in (403, 404) or status_code is None:
                agile_failed = True
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"Jira boards API failed: {body_text or str(exc)}",
                )

        if not raw or agile_failed:
            # Agile API returned zero boards or no Jira Software scope —
            # fall back to project list (works with read:jira-work).
            try:
                projects = await client.get_projects()
            except Exception as proj_exc:
                if agile_failed:
                    raise HTTPException(status_code=502, detail=f"Could not load boards or projects from Jira: {proj_exc}")
                projects = []
            return [
                {
                    "id": f"project-{p['id']}",
                    "name": p["name"],
                    "project_key": p.get("key", ""),
                    "type": "project",
                    "connection_id": str(conn.id),
                }
                for p in projects
            ]

        return [
            {
                "id": str(b["id"]),
                "name": b["name"],
                "project_key": b.get("location", {}).get("projectKey", ""),
                "type": b.get("type", "scrum"),
                "connection_id": str(conn.id),
            }
            for b in raw
        ]

    results = await _asyncio.gather(*[_boards_for_connection(c) for c in connections])
    await db.commit()

    all_boards = [board for site_boards in results for board in site_boards]
    return all_boards


@router.get("/team-members")
async def get_team_members(
    connection_id: str = Query(...),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return TeamMember rows for the team associated with a connection.

    Includes per-member issue count. If no members exist (Celery sync hasn't
    run yet), fetches users from Jira inline and upserts them first.
    """
    import logging as _logging
    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from src.models.developer import TeamMember
    from src.models.ticket import Ticket

    try:
        conn_uuid = uuid.UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id")

    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=403, detail="Access denied")

    connection = await db.get(JiraConnection, conn_uuid)
    if not connection or connection.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Jira connection not found")

    team = await db.scalar(
        select(Team).where(Team.organization_id == org.id)
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found for this organisation")

    existing = (await db.scalars(
        select(TeamMember).where(TeamMember.team_id == team.id)
    )).all()

    if not existing:
        # Inline sync: fetch users from Jira and upsert them.
        access_token = decrypt(connection.encrypted_access_token)
        if connection.token_expires_at and connection.token_expires_at <= datetime.utcnow():
            try:
                refresh_tok = decrypt(connection.encrypted_refresh_token)
                tokens = await refresh_access_token(refresh_tok)
                access_token = tokens["access_token"]
                connection.encrypted_access_token = encrypt(access_token)
                if "refresh_token" in tokens:
                    connection.encrypted_refresh_token = encrypt(tokens["refresh_token"])
                if "expires_in" in tokens:
                    connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Failed to refresh Jira token: {exc}")

        client = JiraClient(cloud_id=connection.jira_cloud_id, access_token=access_token)
        try:
            users = await client.get_users()
        except Exception as exc:
            _logging.getLogger(__name__).error("get_users failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"Failed to fetch Jira users: {exc}")

        for user in users:
            account_id = user.get("accountId")
            if not account_id:
                continue
            stmt = pg_insert(TeamMember).values(
                id=uuid.uuid4(),
                team_id=team.id,
                jira_account_id=account_id,
                display_name=user.get("displayName", account_id),
                email=user.get("emailAddress"),
            ).on_conflict_do_update(
                index_elements=["team_id", "jira_account_id"],
                set_={
                    "display_name": user.get("displayName", account_id),
                    "email": user.get("emailAddress"),
                },
            )
            await db.execute(stmt)
        await db.commit()

        existing = (await db.scalars(
            select(TeamMember).where(TeamMember.team_id == team.id)
        )).all()

    # Build issue counts per member.
    count_rows = (await db.execute(
        select(Ticket.assignee_id, func.count(Ticket.id).label("cnt"))
        .where(Ticket.team_id == team.id, Ticket.assignee_id.isnot(None))
        .group_by(Ticket.assignee_id)
    )).all()
    issue_counts = {row.assignee_id: row.cnt for row in count_rows}

    return [
        {
            "id": str(m.id),
            "name": m.display_name,
            "handle": m.display_name.lower().replace(" ", "."),
            "email": m.email,
            "jira_account_id": m.jira_account_id,
            "issues": issue_counts.get(m.id, 0),
        }
        for m in existing
    ]


class ActivateConnectionRequest(BaseModel):
    connection_id: str


@router.post("/activate")
async def activate_connection(
    body: ActivateConnectionRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Activate one pending connection and deactivate all others for this org."""
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    try:
        target_id = uuid.UUID(body.connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id")
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.organization_id == org.id)
    )
    for conn in result.scalars().all():
        conn.is_active = conn.id == target_id
    await db.commit()
    return {"activated": body.connection_id}


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
    if not connection:
        raise HTTPException(status_code=404, detail="Jira connection not found")

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org or connection.organization_id != org.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # If the chosen connection is still pending (inactive), activate it and
    # deactivate all others — this is the multi-site path where the user
    # implicitly chose a site by picking a board on it.
    if not connection.is_active:
        all_conns = await db.execute(
            select(JiraConnection).where(JiraConnection.organization_id == org.id)
        )
        for conn in all_conns.scalars().all():
            conn.is_active = conn.id == conn_uuid

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
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
):
    """Run Jira sync in a background thread; returns immediately."""
    from src.integrations.jira.sync import sync_jira_team
    background_tasks.add_task(sync_jira_team, team_id)
    return {"status": "syncing"}


@router.get("/sync-status")
async def get_sync_status(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return last_synced_at for the org's active Jira connection."""
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        return {"last_synced_at": None}
    connection = await db.scalar(
        select(JiraConnection).where(
            JiraConnection.organization_id == org.id,
            JiraConnection.is_active == True,
        )
    )
    return {
        "last_synced_at": connection.last_synced_at.isoformat()
        if connection and connection.last_synced_at
        else None
    }
