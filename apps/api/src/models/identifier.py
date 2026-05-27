import enum
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base


class IdentifierSource(enum.Enum):
    """Where a learned identifier was first observed.

    Stored as VARCHAR(30) (no native pg enum) because values are short and the
    set may grow as new sources (e.g. pr_title, comment) are added.
    """
    EPIC               = "epic"
    TICKET_DESCRIPTION = "ticket_description"
    TICKET_TITLE       = "ticket_title"
    LABEL              = "label"
    COMPONENT          = "component"


class TeamIdentifier(Base):
    __tablename__ = "team_identifiers"
    __table_args__ = (
        UniqueConstraint("team_id", "token", name="uq_team_identifier_token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_token: Mapped[str] = mapped_column(Text, nullable=False)
    skill: Mapped[str] = mapped_column(String(100), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class TicketSkillAnalysis(Base):
    __tablename__ = "ticket_skill_analyses"
    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_ticket_skill_analysis"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_vector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    domain_vector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    matched_identifiers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
