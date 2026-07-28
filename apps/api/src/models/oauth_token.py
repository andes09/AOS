import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class OAuthToken(Base):
    """
    Omada-minted opaque bearer token (access or refresh) — never a Clerk JWT.
    `token_hash` is SHA-256 hex of the opaque bearer string, hashed (never
    reversibly encrypted): Omada only ever needs to VERIFY a token presented
    back to it, never present one to a third party, so a one-way hash is
    correct here — the opposite direction from `OAuthClient.client_secret_enc`
    above, which the SDK needs decrypted for a plaintext comparison.

    `developer_id` is re-resolved fresh from the DB on every tool call (never
    trusted stale off a cached claim), so a role change or org removal takes
    effect immediately without needing token revocation.

    `parent_token_id` links a refresh token to the access token it was issued
    alongside, so revoking one can cascade to the other.
    """

    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    token_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "access" | "refresh"
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("oauth_clients.client_id"), index=True
    )
    clerk_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    clerk_org_id: Mapped[str] = mapped_column(String(255), nullable=False)
    developer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developers.id"), nullable=False, index=True
    )
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oauth_tokens.id"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
