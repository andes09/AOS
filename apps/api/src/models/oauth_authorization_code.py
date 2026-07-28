import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class OAuthAuthorizationCode(Base):
    """
    Short-TTL, one-time-use authorization code (RFC 6749 §4.1 + PKCE, RFC
    7636) minted by `POST /api/mcp/oauth/consent` once a Clerk-signed-in user
    approves an MCP client. `developer_id` is NOT nullable (unlike
    clerk_user_id being enough on its own): MCP tool calls need a real
    `Developer` row to assign tasks to and check roles against, so the
    consent endpoint 409s before ever reaching this table if the connecting
    Clerk user has no Developer record (see mcp_oauth_consent.py) — same
    posture call-out as the plan doc's risk #1.

    PKCE verification, expiry, and redirect_uri-match are all done by the SDK
    itself (mcp.server.auth.handlers.token.TokenHandler) before
    OmadaOAuthProvider.exchange_authorization_code is ever called — this
    table just needs to durably hold what the SDK needs to check those, plus
    `used_at` for one-time-use enforcement (belt-and-suspenders: the SDK
    doesn't re-check use, so exchange_authorization_code marks this itself).
    """

    __tablename__ = "oauth_authorization_codes"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("oauth_clients.client_id"), index=True
    )
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    code_challenge: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clerk_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    clerk_org_id: Mapped[str] = mapped_column(String(255), nullable=False)
    developer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developers.id"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
