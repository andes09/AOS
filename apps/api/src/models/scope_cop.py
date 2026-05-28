import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, Enum as SAEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base


_JSONB_OR_JSON = JSON().with_variant(JSONB(), "postgresql")


class ScopeCopStatus(enum.Enum):
    READY      = "ready"
    NEEDS_WORK = "needs_work"
    BLOCKED    = "blocked"


class TicketAnalysis(Base):
    __tablename__ = "ticket_analyses"
    __table_args__ = (
        UniqueConstraint("team_id", "ticket_key", name="uq_ticket_analysis"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    ticket_key: Mapped[str] = mapped_column(String(50), nullable=False)
    ticket_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    readiness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(ScopeCopStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    issues: Mapped[list | None] = mapped_column(_JSONB_OR_JSON, nullable=True)
    suggestions: Mapped[list | None] = mapped_column(_JSONB_OR_JSON, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
