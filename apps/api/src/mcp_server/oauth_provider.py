"""
OmadaOAuthProvider — a thin OAuth 2.1 Authorization Server implementing
`mcp.server.auth.provider.OAuthAuthorizationServerProvider`, so MCP clients
(Claude Code, Claude Desktop, Cursor, ...) can connect directly to a user's
Omada roadmap. Clerk does the actual login (see routers/mcp_oauth_consent.py
— that's the one point where a Clerk JWT satisfies this flow); everything
here issues Omada's own opaque bearer tokens, never a Clerk JWT.

Carrying `clerk_org_id`/`clerk_user_id`/`developer_id` into tool-handler
context: `AccessToken` (mcp.shared.auth) already has a builtin
`claims: dict[str, Any] | None` field, and `get_access_token()`
(mcp.server.auth.middleware.auth_context) returns the exact object this
provider constructs in `load_access_token` — no subclassing needed. Verified
by reading `AuthenticatedUser.__init__`, which stores the object as-is.

`client_secret` is the one place this provider deals with a REVERSIBLE
secret rather than a hash: the SDK's own client authenticator compares it in
plaintext via `hmac.compare_digest`, so `oauth_clients.client_secret_enc` is
Fernet-encrypted (`src/services/encryption.py`), not hashed — see
`src/models/oauth_client.py`'s docstring. Bearer tokens (`oauth_tokens.
token_hash`) go the other way: Omada only ever verifies them, so they're
hashed one-way.
"""

import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select

from src.config import settings
from src.database import db_session
from src.models.developer import Developer
from src.models.oauth_authorization_code import OAuthAuthorizationCode
from src.models.oauth_client import OAuthClient
from src.models.oauth_token import OAuthToken as OAuthTokenModel
from src.models.organization import Organization
from src.models.team import Team
from src.services.encryption import decrypt, encrypt

# 1h access tokens, 90d refresh — long-lived roadmap-scoped credentials, but
# a fresh developer_id/role lookup happens on every tool call regardless (see
# tools.py), so a stale token can't outlive a role change or removal.
_ACCESS_TOKEN_TTL_SECONDS = 60 * 60
_REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 90
_AUTH_CODE_TTL_SECONDS = 120


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


class OmadaOAuthProvider:
    """Duck-types `OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]`."""

    # ─── client registration (RFC 7591) ─────────────────────────────────────
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with db_session() as db:
            row = await db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
        if row is None:
            return None
        return OAuthClientInformationFull(
            client_id=row.client_id,
            client_secret=decrypt(row.client_secret_enc) if row.client_secret_enc else None,
            client_id_issued_at=row.client_id_issued_at,
            client_secret_expires_at=row.client_secret_expires_at,
            redirect_uris=row.redirect_uris,
            grant_types=row.grant_types,
            response_types=row.response_types or ["code"],
            token_endpoint_auth_method=row.token_endpoint_auth_method,
            client_name=row.client_name,
            scope=row.scope,
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        client_id = client_info.client_id or f"mcp_{uuid.uuid4().hex}"
        async with db_session() as db:
            existing = await db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
            if existing is not None:
                raise RegistrationError(error="invalid_client_metadata", error_description="client_id already registered")
            db.add(OAuthClient(
                client_id=client_id,
                client_secret_enc=encrypt(client_info.client_secret) if client_info.client_secret else None,
                client_name=client_info.client_name,
                redirect_uris=[str(u) for u in client_info.redirect_uris],
                grant_types=client_info.grant_types,
                response_types=client_info.response_types or ["code"],
                token_endpoint_auth_method=client_info.token_endpoint_auth_method or "none",
                scope=client_info.scope,
                client_id_issued_at=client_info.client_id_issued_at or int(time.time()),
                client_secret_expires_at=client_info.client_secret_expires_at,
            ))
            await db.commit()
        # The SDK expects register_client to have populated client_id/issued_at
        # onto the same object it passed in (it re-reads these after calling us).
        client_info.client_id = client_id
        client_info.client_id_issued_at = client_info.client_id_issued_at or int(time.time())

    # ─── authorize (redirects the browser into apps/web's Clerk-gated consent page) ─
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if client.client_id is None:
            raise AuthorizeError(error="invalid_client")
        query = {
            "client_id": client.client_id,
            "client_name": client.client_name or "An MCP client",
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(params.scopes or []),
            "state": params.state or "",
        }
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        return f"{settings.frontend_url}/mcp/authorize?{qs}"

    # ─── authorization codes ────────────────────────────────────────────────
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with db_session() as db:
            row = await db.scalar(
                select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == authorization_code)
            )
            if row is None or row.client_id != client.client_id or row.used_at is not None:
                return None
            if row.expires_at < datetime.utcnow():
                return None
            return AuthorizationCode(
                code=row.code,
                scopes=(row.scope or "").split() if row.scope else [],
                expires_at=row.expires_at.timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=row.redirect_uri,
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                subject=row.developer_id.hex,
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        async with db_session() as db:
            row = await db.scalar(
                select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == authorization_code.code)
            )
            if row is None or row.used_at is not None:
                raise TokenError(error="invalid_grant", error_description="authorization code already used or unknown")
            row.used_at = datetime.utcnow()

            access_raw, refresh_raw = _new_opaque_token(), _new_opaque_token()
            now = datetime.utcnow()
            access_id = uuid.uuid4()
            db.add(OAuthTokenModel(
                id=access_id, token_hash=_hash_token(access_raw), token_type="access",
                client_id=client.client_id, clerk_user_id=row.clerk_user_id, clerk_org_id=row.clerk_org_id,
                developer_id=row.developer_id, scope=row.scope,
                expires_at=now + timedelta(seconds=_ACCESS_TOKEN_TTL_SECONDS),
            ))
            db.add(OAuthTokenModel(
                id=uuid.uuid4(), token_hash=_hash_token(refresh_raw), token_type="refresh",
                client_id=client.client_id, clerk_user_id=row.clerk_user_id, clerk_org_id=row.clerk_org_id,
                developer_id=row.developer_id, scope=row.scope, parent_token_id=access_id,
                expires_at=now + timedelta(seconds=_REFRESH_TOKEN_TTL_SECONDS),
            ))
            await db.commit()

        return OAuthToken(
            access_token=access_raw,
            refresh_token=refresh_raw,
            expires_in=_ACCESS_TOKEN_TTL_SECONDS,
            scope=row.scope,
        )

    # ─── refresh tokens ──────────────────────────────────────────────────────
    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        async with db_session() as db:
            row = await db.scalar(
                select(OAuthTokenModel).where(OAuthTokenModel.token_hash == _hash_token(refresh_token))
            )
            if row is None or row.token_type != "refresh" or row.revoked_at is not None:
                return None
            if row.client_id != client.client_id or row.expires_at < datetime.utcnow():
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=(row.scope or "").split() if row.scope else [],
                expires_at=int(row.expires_at.timestamp()),
                subject=row.developer_id.hex,
            )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        async with db_session() as db:
            old_refresh = await db.scalar(
                select(OAuthTokenModel).where(OAuthTokenModel.token_hash == _hash_token(refresh_token.token))
            )
            if old_refresh is None or old_refresh.revoked_at is not None:
                raise TokenError(error="invalid_grant", error_description="refresh token revoked or unknown")

            now = datetime.utcnow()
            # Rotate both — revoke the old pair, mint a fresh one.
            old_refresh.revoked_at = now
            if old_refresh.parent_token_id is not None:
                old_access = await db.scalar(
                    select(OAuthTokenModel).where(OAuthTokenModel.id == old_refresh.parent_token_id)
                )
                if old_access is not None:
                    old_access.revoked_at = now

            access_raw, new_refresh_raw = _new_opaque_token(), _new_opaque_token()
            access_id = uuid.uuid4()
            scope = " ".join(scopes) if scopes else old_refresh.scope
            db.add(OAuthTokenModel(
                id=access_id, token_hash=_hash_token(access_raw), token_type="access",
                client_id=client.client_id, clerk_user_id=old_refresh.clerk_user_id,
                clerk_org_id=old_refresh.clerk_org_id, developer_id=old_refresh.developer_id, scope=scope,
                expires_at=now + timedelta(seconds=_ACCESS_TOKEN_TTL_SECONDS),
            ))
            db.add(OAuthTokenModel(
                id=uuid.uuid4(), token_hash=_hash_token(new_refresh_raw), token_type="refresh",
                client_id=client.client_id, clerk_user_id=old_refresh.clerk_user_id,
                clerk_org_id=old_refresh.clerk_org_id, developer_id=old_refresh.developer_id, scope=scope,
                parent_token_id=access_id, expires_at=now + timedelta(seconds=_REFRESH_TOKEN_TTL_SECONDS),
            ))
            await db.commit()

        return OAuthToken(
            access_token=access_raw, refresh_token=new_refresh_raw,
            expires_in=_ACCESS_TOKEN_TTL_SECONDS, scope=scope,
        )

    # ─── access tokens ───────────────────────────────────────────────────────
    async def load_access_token(self, token: str) -> AccessToken | None:
        async with db_session() as db:
            row = await db.scalar(
                select(OAuthTokenModel).where(OAuthTokenModel.token_hash == _hash_token(token))
            )
            if row is None or row.token_type != "access" or row.revoked_at is not None:
                return None
            if row.expires_at < datetime.utcnow():
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=(row.scope or "").split() if row.scope else [],
                expires_at=int(row.expires_at.timestamp()),
                subject=row.developer_id.hex,
                # Carried into tool-handler context via get_access_token().claims
                # (see module docstring) — resolved fresh on every tool call,
                # never trusted as the sole source of truth for authorization.
                claims={
                    "clerk_org_id": row.clerk_org_id,
                    "clerk_user_id": row.clerk_user_id,
                    "developer_id": str(row.developer_id),
                },
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with db_session() as db:
            row = await db.scalar(
                select(OAuthTokenModel).where(OAuthTokenModel.token_hash == _hash_token(token.token))
            )
            if row is None:
                return
            now = datetime.utcnow()
            row.revoked_at = now
            # Cascade: revoking an access token also revokes its refresh token
            # and vice versa (whichever side owns the parent_token_id link).
            if row.parent_token_id is not None:
                sibling = await db.scalar(select(OAuthTokenModel).where(OAuthTokenModel.id == row.parent_token_id))
                if sibling is not None:
                    sibling.revoked_at = now
            else:
                child = await db.scalar(select(OAuthTokenModel).where(OAuthTokenModel.parent_token_id == row.id))
                if child is not None:
                    child.revoked_at = now
            await db.commit()


async def resolve_developer(clerk_org_id: str, clerk_user_id: str) -> Developer | None:
    """Shared by mcp_oauth_consent.py (409s if this returns None — see risk #1
    in the plan doc) and tools.py (re-resolves fresh on every call)."""
    async with db_session() as db:
        return await db.scalar(
            select(Developer)
            .join(Team, Developer.team_id == Team.id)
            .join(Organization, Team.organization_id == Organization.id)
            .where(Organization.clerk_org_id == clerk_org_id, Developer.clerk_user_id == clerk_user_id)
        )
