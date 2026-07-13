"""
GitHub integration routes (onboarding v2 — repo access for the roadmap AI).

GET    /api/integrations/github/connect     → returns GitHub OAuth authorization URL
GET    /api/integrations/github/callback    → handles OAuth code exchange, saves connection
GET    /api/integrations/github/status      → returns connection status for the current org
DELETE /api/integrations/github/disconnect  → deactivates the connection
GET    /api/integrations/github/repos       → lists repos the connection can access
"""

import logging
import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id, get_current_org_id
from src.config import settings
from src.database import get_db
from src.integrations.github.client import GithubClient
from src.integrations.github.oauth import exchange_code_for_tokens, get_authorization_url
from src.models.github_connection import GithubConnection
from src.models.oauth_state import OAuthState
from src.models.organization import Organization
from src.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/github", tags=["github"])


async def _get_org(clerk_org_id: str, db: AsyncSession) -> Organization | None:
    return await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )


async def get_active_connection(
    org: Organization, db: AsyncSession
) -> GithubConnection | None:
    return await db.scalar(
        select(GithubConnection).where(
            GithubConnection.organization_id == org.id,
            GithubConnection.is_active == True,
        )
    )


@router.get("/connect")
async def github_connect(
    return_to: str = Query(default="/onboarding"),
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the GitHub OAuth authorization URL."""
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


def _error_redirect(return_to: str, reason: str) -> RedirectResponse:
    frontend_base = settings.frontend_url.split(",")[0].strip().rstrip("/")
    return RedirectResponse(f"{frontend_base}{return_to}?github=error&reason={reason}")


@router.get("/callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    GitHub redirects here after the user grants access. Exchanges the code for
    a token, resolves the org from the state token, and persists the connection.
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
    connected_by = state_row.user_id
    return_to = state_row.return_to
    await db.delete(state_row)

    org = await _get_org(clerk_org_id, db)
    if not org:
        await db.commit()
        return _error_redirect(return_to, "org_not_provisioned")

    try:
        tokens = await exchange_code_for_tokens(code)
    except httpx.HTTPError:
        logger.exception("GitHub token exchange failed")
        await db.commit()
        return _error_redirect(return_to, "token_exchange_failed")
    access_token = tokens.get("access_token")
    if not access_token:
        # GitHub reports errors (bad_verification_code etc.) in a 200 body.
        logger.warning("GitHub token exchange returned error: %s", tokens.get("error"))
        await db.commit()
        return _error_redirect(return_to, tokens.get("error", "token_exchange_failed"))

    try:
        gh_user = await GithubClient(access_token).get_user()
    except httpx.HTTPError:
        logger.exception("GitHub /user fetch failed")
        await db.commit()
        return _error_redirect(return_to, "user_fetch_failed")

    expires_at = None
    if "expires_in" in tokens:
        expires_at = datetime.utcnow() + timedelta(seconds=int(tokens["expires_in"]))

    # Deactivate existing active connections for this org before inserting.
    existing = await db.execute(
        select(GithubConnection).where(
            GithubConnection.organization_id == org.id,
            GithubConnection.is_active == True,
        )
    )
    for conn in existing.scalars().all():
        conn.is_active = False

    db.add(GithubConnection(
        organization_id=org.id,
        github_user_id=str(gh_user["id"]),
        github_login=gh_user["login"],
        avatar_url=gh_user.get("avatar_url"),
        encrypted_access_token=encrypt(access_token),
        encrypted_refresh_token=encrypt(tokens["refresh_token"]) if tokens.get("refresh_token") else None,
        token_expires_at=expires_at,
        scopes=(tokens.get("scope") or "").split(",") if tokens.get("scope") else [],
        is_active=True,
        connected_by_user_id=connected_by,
    ))
    await db.commit()

    frontend_base = settings.frontend_url.split(",")[0].strip().rstrip("/")
    return RedirectResponse(f"{frontend_base}{return_to}?github=connected")


@router.get("/status")
async def github_status(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return whether the current org has an active GitHub connection."""
    org = await _get_org(clerk_org_id, db)
    if not org:
        return {"connected": False}

    connection = await get_active_connection(org, db)
    if not connection:
        return {"connected": False}

    return {
        "connected": True,
        "login": connection.github_login,
        "avatarUrl": connection.avatar_url,
        "scopes": connection.scopes or [],
        "connectedAt": connection.created_at.isoformat(),
    }


@router.delete("/disconnect")
async def github_disconnect(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the org's GitHub connection."""
    org = await _get_org(clerk_org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    connection = await get_active_connection(org, db)
    if not connection:
        raise HTTPException(status_code=404, detail="No active GitHub connection found")
    connection.is_active = False
    await db.commit()
    return {"disconnected": True}


@router.get("/repos")
async def github_repos(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List repos accessible to the org's GitHub connection."""
    org = await _get_org(clerk_org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    connection = await get_active_connection(org, db)
    if not connection:
        raise HTTPException(status_code=404, detail="No active GitHub connection found")

    client = GithubClient(decrypt(connection.encrypted_access_token))
    try:
        repos = await client.list_repos(page=page, per_page=per_page)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            # Token revoked on GitHub's side — surface as a broken connection.
            connection.is_active = False
            await db.commit()
            raise HTTPException(status_code=502, detail="GitHub token no longer valid — reconnect GitHub")
        raise HTTPException(status_code=502, detail="GitHub API request failed")

    return [
        {
            "id": r["id"],
            "fullName": r["full_name"],
            "private": r["private"],
            "defaultBranch": r.get("default_branch"),
            "url": r["html_url"],
        }
        for r in repos
    ]
