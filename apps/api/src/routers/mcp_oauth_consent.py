"""
POST /api/mcp/oauth/consent — the one point where Clerk's existing login
satisfies the MCP OAuth flow. Depends on the *existing* Clerk deps
(get_current_user_id/get_current_org_id), resolves the caller's Developer,
validates the client/redirect_uri, mints an authorization code, and returns
the redirect URL for the frontend consent page (McpAuthorizePage.tsx) to
follow — completing the `/authorize` -> browser -> here -> back to the MCP
client's redirect_uri round trip described in oauth_provider.py.

Gated behind `experimental.mcp_server`, same posture as the other stages'
flag-gated routers.
"""

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from mcp.server.auth.provider import construct_redirect_uri
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id, get_current_user_id
from src.config import settings
from src.database import get_db
from src.mcp_server.oauth_provider import resolve_developer
from src.models.oauth_authorization_code import OAuthAuthorizationCode
from src.models.oauth_client import OAuthClient

_AUTH_CODE_TTL_SECONDS = 120


def _require_mcp_server_enabled() -> None:
    if not settings.is_feature_enabled("experimental.mcp_server"):
        raise HTTPException(status_code=404, detail="not_found")


router = APIRouter(
    prefix="/api/mcp",
    tags=["mcp-oauth-consent"],
    dependencies=[Depends(_require_mcp_server_enabled)],
)


class ConsentRequest(BaseModel):
    clientId: str
    redirectUri: str
    codeChallenge: str
    scope: str | None = None
    state: str | None = None


@router.post("/oauth/consent")
async def consent(
    body: ConsentRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(OAuthClient).where(OAuthClient.client_id == body.clientId))
    if client is None:
        raise HTTPException(status_code=404, detail="unknown_client")
    if body.redirectUri not in (client.redirect_uris or []):
        raise HTTPException(status_code=400, detail="redirect_uri_mismatch")

    # Open risk #1 from the plan doc: a connecting Clerk user with no
    # Developer row can't be minted a usable token (MCP needs a real
    # developer_id to assign tasks to and to mint tokens against) — reject
    # here with a clear 409 rather than mirroring the REST-side "default to
    # developer role" behavior get_current_app_role uses.
    developer = await resolve_developer(clerk_org_id, user_id)
    if developer is None:
        raise HTTPException(status_code=409, detail="no_developer_record")

    code = secrets.token_urlsafe(32)
    db.add(OAuthAuthorizationCode(
        code=code,
        client_id=client.client_id,
        redirect_uri=body.redirectUri,
        code_challenge=body.codeChallenge,
        scope=body.scope,
        clerk_user_id=user_id,
        clerk_org_id=clerk_org_id,
        developer_id=developer.id,
        expires_at=datetime.utcnow() + timedelta(seconds=_AUTH_CODE_TTL_SECONDS),
    ))
    await db.commit()

    redirect_url = construct_redirect_uri(body.redirectUri, code=code, state=body.state)
    return {"redirectUrl": redirect_url}
