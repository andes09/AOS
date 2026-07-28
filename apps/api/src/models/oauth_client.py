from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class OAuthClient(Base):
    """
    Dynamically-registered MCP client (RFC 7591 Dynamic Client Registration).
    Populated by OmadaOAuthProvider.register_client the first time a coding
    agent (Claude Code, Claude Desktop, Cursor, ...) connects — no manual
    provisioning, mirroring how every other MCP-compatible server works.

    `client_secret_enc` is reversibly ENCRYPTED (Fernet, via
    src/services/encryption.py), not hashed — a deliberate deviation from the
    original plan's "client_secret_hash". The MCP SDK's own
    `ClientAuthenticator` (mcp.server.auth.middleware.client_auth) compares
    this value with `hmac.compare_digest` against the plaintext secret
    presented at `/token`, so a one-way hash could never match; this needs
    the same reversible-encryption treatment as `Organization.
    encrypted_anthropic_key` / GithubConnection's tokens, not the same
    treatment as `OAuthToken.token_hash` below (which Omada only ever
    verifies, never presents back, so hashing is correct there). NULL for
    public PKCE clients registered with token_endpoint_auth_method="none" —
    the common case; MCP clients don't get issued a secret at all in that
    mode.
    """

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_uris: Mapped[list] = mapped_column(JSON, nullable=False)
    grant_types: Mapped[list] = mapped_column(JSON, nullable=False)
    response_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    token_endpoint_auth_method: Mapped[str] = mapped_column(
        String(30), default="none", server_default="none"
    )
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id_issued_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_secret_expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
