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


# Documented granular scopes per endpoint we hit. Used purely for diagnostic
# logging when Atlassian returns 401 "scope does not match" — the body never
# names the missing scope, so we compute the diff against the granted token
# scopes and surface it in the API log.
_REQUIRED_SCOPES = {
    # get_projects now derives projects from /agile/1.0/board (the Platform-side
    # /project/search was edge-denied with FAILURE_CLIENT_SCOPE_CHECK even with
    # every documented scope granted), so the expected scope is the same as for
    # the boards endpoint.
    "project_search": ["read:board-scope:jira-software"],
    "boards_for_project": ["read:board-scope:jira-software", "read:project:jira"],
}


def _log_scope_diagnostics(
    logger,
    endpoint_label: str,
    conn: "JiraConnection",
    body_text: str,
    resp=None,
) -> None:
    """When Jira returns "scope does not match", log granted vs. expected scopes.

    The Jira 401 body never names the missing scope. This helper diffs the
    token's granted scope list (stored on JiraConnection at OAuth callback)
    against the scopes Atlassian's docs require for the failing endpoint,
    and also logs the WWW-Authenticate header (per OAuth 2.0 spec it should
    name the missing scope) — which is the only authoritative signal when
    the documented scope set turns out to be incomplete.
    """
    if "scope does not match" not in (body_text or "").lower():
        return
    expected = _REQUIRED_SCOPES.get(endpoint_label, [])
    granted = list(conn.scopes or [])
    missing = [s for s in expected if s not in granted]
    # Atlassian sometimes includes the required scope in WWW-Authenticate
    # ("Bearer scope=\"read:foo:bar\""). Log every response header so we
    # can see what Atlassian is actually telling us about the denial.
    headers_dump = ""
    if resp is not None:
        try:
            headers_dump = "; ".join(f"{k}={v}" for k, v in resp.headers.items())
        except Exception:
            headers_dump = "(failed to read headers)"
    logger.warning(
        "scope diagnostic for %s on %s — granted=%s expected=%s missing=%s | response_headers: %s",
        endpoint_label,
        conn.jira_cloud_url,
        granted,
        expected,
        missing or "(none — Atlassian denied for non-scope reason)",
        headers_dump or "(no response object)",
    )


def _run_sync_in_process(team_id: str) -> None:
    """Wrapper that runs sync_jira_team in the current thread and surfaces errors.

    sync_jira_team is a bind=True Celery task whose except branch calls
    self.retry(), which raises a Retry exception. Outside a Celery worker there
    is nothing to handle that Retry — it propagates into FastAPI BackgroundTasks
    and disappears silently, leaving the user staring at a "Sync" button that
    never completes. Catching all exceptions here turns silent failures into
    log lines that name the team and the actual cause.
    """
    import logging as _bg_log
    from src.integrations.jira.sync import sync_jira_team
    _log = _bg_log.getLogger(__name__)
    try:
        sync_jira_team(team_id)
    except Exception as exc:
        _log.exception(
            "in-process Jira sync failed for team %s: %s", team_id, exc,
        )


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

    import logging as _cb_log
    _cb_log.getLogger(__name__).info(
        "OAuth callback — granted scopes: %s | resource ids: %s",
        tokens.get("scope"),
        [r.get("id") for r in resources],
    )

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

    frontend_base = settings.frontend_url.split(",")[0].strip().rstrip("/")
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

    team = await db.scalar(select(Team).where(Team.organization_id == org.id))
    board_id = team.jira_board_id if team else None
    board_ok = bool(board_id and not board_id.startswith("project-"))

    return {
        "connected": True,
        "cloud_url": connection.jira_cloud_url,
        "last_synced_at": connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        "board_id": board_id,
        "board_configured": board_ok,
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


async def _resolve_jira_connections(
    db: AsyncSession,
    org: Organization,
    connection_id: str | None,
    connection_ids: str | None,
) -> list[JiraConnection]:
    """Resolve a single connection_id or comma-separated connection_ids to JiraConnection rows.

    Raises HTTPException on bad input or unknown connection.
    """
    if connection_ids:
        ids = [s.strip() for s in connection_ids.split(",") if s.strip()]
        result = await db.execute(
            select(JiraConnection).where(
                JiraConnection.id.in_([uuid.UUID(i) for i in ids]),
                JiraConnection.organization_id == org.id,
            )
        )
        return list(result.scalars().all())
    if connection_id:
        try:
            conn_uuid = uuid.UUID(connection_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid connection_id")
        connection = await db.get(JiraConnection, conn_uuid)
        if not connection or connection.organization_id != org.id:
            raise HTTPException(status_code=404, detail="Jira connection not found")
        return [connection]
    raise HTTPException(status_code=400, detail="connection_id or connection_ids required")


async def _authed_jira_client(conn: JiraConnection) -> JiraClient | None:
    """Build a JiraClient for a connection, refreshing the token if expired.

    Returns None if token refresh fails (caller should treat the site as
    unreachable rather than aborting the whole request).
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

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
            _log.warning("Token refresh failed for %s: %s", conn.jira_cloud_url, exc)
            return None
    return JiraClient(cloud_id=conn.jira_cloud_id, access_token=access_token)


@router.get("/projects")
async def get_jira_projects(
    connection_id: str = Query(default=None),
    connection_ids: str = Query(default=None),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List Jira projects visible to the connection(s).

    Onboarding is project-first: user picks a project, then picks a board
    within that project (see GET /boards?project_key=…). Returns
    {id, key, name, connection_id} per project, aggregated across all
    connections when ?connection_ids= is supplied.
    """
    import asyncio as _asyncio
    import logging as _logging

    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=403, detail="Access denied")

    connections = await _resolve_jira_connections(db, org, connection_id, connection_ids)
    _log = _logging.getLogger(__name__)

    # Track per-site failures so we can fall back to a 502 only when EVERY
    # connection failed. With multi-site OAuth, a single restricted/admin-only
    # site shouldn't hide projects from the user's other working sites.
    site_failures: list[tuple[str, int | None]] = []

    async def _projects_for_connection(conn: JiraConnection) -> list[dict]:
        client = await _authed_jira_client(conn)
        if client is None:
            site_failures.append((conn.jira_cloud_url, None))
            return []
        try:
            projects = await client.get_projects()
        except Exception as exc:
            resp = getattr(exc, "response", None)
            status_code = getattr(resp, "status_code", None) if resp else None
            body_text = ""
            if resp is not None:
                try:
                    body_text = resp.text[:400]
                except Exception:
                    pass
            _log.warning(
                "get_projects failed for %s (status=%s): %s",
                conn.jira_cloud_url, status_code, body_text or exc,
            )
            _log_scope_diagnostics(_log, "project_search", conn, body_text, resp)
            site_failures.append((conn.jira_cloud_url, status_code))
            return []
        return [
            {
                "id": str(p["id"]),
                "key": p.get("key", ""),
                "name": p["name"],
                "connection_id": str(conn.id),
            }
            for p in projects
        ]

    results = await _asyncio.gather(
        *[_projects_for_connection(c) for c in connections],
        return_exceptions=True,
    )
    await db.commit()

    all_projects: list[dict] = []
    for site_result in results:
        if isinstance(site_result, list):
            all_projects.extend(site_result)
        else:
            _log.warning("_projects_for_connection raised unexpectedly: %s", site_result)

    # Only raise 502 when we got nothing AND every connection failed with an
    # auth/scope error. Otherwise the user can still pick from working sites.
    if not all_projects and connections and len(site_failures) == len(connections):
        auth_failures = [f for f in site_failures if f[1] in (401, 403)]
        if auth_failures:
            sites = ", ".join(url for url, _ in auth_failures)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Jira denied project access on {len(auth_failures)} of "
                    f"{len(connections)} connected site(s) ({sites}). Disconnect "
                    "and reconnect Jira to re-grant access, or check that your "
                    "Atlassian account has project-browse permission on at least "
                    "one site."
                ),
            )

    return all_projects


@router.get("/boards")
async def get_jira_boards(
    project_key: str = Query(..., description="Jira project key the boards belong to"),
    connection_id: str = Query(default=None),
    connection_ids: str = Query(default=None),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List Scrum/Kanban boards within a single Jira project.

    project_key is required: onboarding always picks a project before a board,
    so we scope the Agile board query to that project. This avoids the old
    "list every board the token can see" fallback that returned synthetic
    project-* identifiers when the Agile API came up empty (those weren't
    usable as board IDs and produced 401s during sync).
    """
    import asyncio as _asyncio
    import logging as _logging

    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=403, detail="Access denied")

    connections = await _resolve_jira_connections(db, org, connection_id, connection_ids)
    _log = _logging.getLogger(__name__)

    async def _boards_for_connection(conn: JiraConnection) -> list[dict]:
        client = await _authed_jira_client(conn)
        if client is None:
            return []
        try:
            raw = await client.get_boards_for_project(project_key)
        except Exception as exc:
            resp = getattr(exc, "response", None)
            status_code = getattr(resp, "status_code", None) if resp else None
            body_text = ""
            if resp is not None:
                try:
                    body_text = resp.text[:400]
                except Exception:
                    pass
            _log.warning(
                "get_boards_for_project(%s) failed for %s (status=%s): %s",
                project_key, conn.jira_cloud_url, status_code, body_text or exc,
            )
            _log_scope_diagnostics(_log, "boards_for_project", conn, body_text, resp)
            if "suspended" in body_text.lower():
                return []
            if status_code in (401, 403):
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Jira denied access to boards for this project. Your connection "
                        "may be missing the 'Jira Software' product — disconnect Jira "
                        "and reconnect to re-grant access."
                    ),
                )
            return []
        return [
            {
                "id": str(b["id"]),
                "name": b["name"],
                "project_key": b.get("location", {}).get("projectKey", "") or project_key,
                "type": b.get("type", "scrum"),
                "connection_id": str(conn.id),
            }
            for b in raw
        ]

    results = await _asyncio.gather(
        *[_boards_for_connection(c) for c in connections],
        return_exceptions=True,
    )
    await db.commit()

    all_boards: list[dict] = []
    for site_result in results:
        if isinstance(site_result, HTTPException):
            raise site_result
        elif isinstance(site_result, list):
            all_boards.extend(site_result)
        else:
            _log.warning("_boards_for_connection raised unexpectedly: %s", site_result)

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
    from sqlalchemy import func, update as sa_update
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from src.models.developer import Developer
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

    # Always re-sync from Jira so stale service/bot accounts are purged.
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

    fresh_account_ids: set[str] = set()
    for user in users:
        account_id = user.get("accountId")
        if not account_id:
            continue
        fresh_account_ids.add(account_id)
        display_name = user.get("displayName", account_id)
        email = user.get("emailAddress")
        stmt = pg_insert(Developer).values(
            id=uuid.uuid4(),
            team_id=team.id,
            jira_account_id=account_id,
            name=display_name,
            email=email,
            is_active=True,
            app_role="developer",
        ).on_conflict_do_update(
            index_elements=["team_id", "jira_account_id"],
            index_where=Developer.jira_account_id.isnot(None),
            set_={"name": display_name, "email": email},
        )
        await db.execute(stmt)

    # Handle accounts no longer returned by Jira (bot/service accounts removed):
    # — Jira-only rows (no Clerk account) are deleted entirely.
    # — Rows with a Clerk account just have their jira_account_id nulled out.
    if fresh_account_ids:
        await db.execute(
            delete(Developer).where(
                Developer.team_id == team.id,
                Developer.jira_account_id.isnot(None),
                Developer.jira_account_id.notin_(fresh_account_ids),
                Developer.clerk_user_id.is_(None),
            )
        )
        await db.execute(
            sa_update(Developer).where(
                Developer.team_id == team.id,
                Developer.jira_account_id.isnot(None),
                Developer.jira_account_id.notin_(fresh_account_ids),
                Developer.clerk_user_id.isnot(None),
            ).values(jira_account_id=None)
        )
    await db.commit()

    existing = (await db.scalars(
        select(Developer).where(
            Developer.team_id == team.id,
            Developer.jira_account_id.isnot(None),
        )
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
            "id": str(d.id),
            "name": d.name,
            "handle": d.name.lower().replace(" ", "."),
            "email": d.email,
            "jira_account_id": d.jira_account_id,
            "issues": issue_counts.get(d.id, 0),
        }
        for d in existing
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
    background_tasks: BackgroundTasks,
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

    import logging as _sync_log
    team_id_str = str(team.id)
    # Always run the onboarding sync in-process. The previous Celery-first
    # design only fell back to in-process when .delay() *raised* (broker
    # unreachable). It did NOT catch the much more common failure: broker
    # reachable but no worker consuming the queue (worker dyno crashed,
    # pointed at a different REDIS_URL, or simply not deployed). In that
    # case the message sat in Redis forever and the user stared at a
    # spinner that never completed. The user is waiting in the UI here —
    # running in-process is what we actually want.
    background_tasks.add_task(_run_sync_in_process, team_id_str)
    _sync_log.getLogger(__name__).info(
        "board-selection: in-process sync scheduled for team %s", team_id_str,
    )

    return {"saved": True, "team_id": team_id_str}


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
    background_tasks.add_task(_run_sync_in_process, team_id)
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


@router.get("/sync-status/{team_id}")
async def get_team_sync_status(
    team_id: str,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return structured SyncStatus for a team (state, timestamps, counts)."""
    from src.models.sync_status import SyncStatus

    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        team_uuid = uuid.UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid team_id")

    team = await db.scalar(select(Team).where(Team.id == team_uuid, Team.organization_id == org.id))
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    row = await db.get(SyncStatus, team_uuid)
    if not row:
        return {"state": "unknown", "tickets_synced": 0, "members_synced": 0}

    return {
        "state": row.state,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "tickets_synced": row.tickets_synced,
        "members_synced": row.members_synced,
    }
