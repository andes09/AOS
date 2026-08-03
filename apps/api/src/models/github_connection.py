import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class GithubConnection(Base):
    __tablename__ = "github_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    installation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_user_id: Mapped[str] = mapped_column(String(255))
    github_login: Mapped[str] = mapped_column(String(255))
    # The installation account's type: "User" or "Organization" (from the
    # GitHub installation object's account.type). Null for connections made
    # before this was captured. Gates API repo-creation: only "Organization"
    # installs can create repos with the installation token (see
    # onboarding_v2.create_repo / integrations/github/client.create_repo).
    account_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Tokens stored encrypted. GitHub App installation tokens expire hourly and
    # are refreshed via installation_id (see router._get_valid_access_token);
    # there's no user refresh token for installation tokens, so that column
    # stays NULL. installation_id is NULL for pre-migration OAuth connections,
    # which are treated as needing reconnect (see /status's needsReconnect).
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    connected_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="github_connections")
