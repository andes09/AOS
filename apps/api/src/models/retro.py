import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Index, JSON
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base


_JSONB_OR_JSON = JSON().with_variant(JSONB(), "postgresql")


class PatternType(enum.Enum):
    OVER_COMMITMENT    = "over_commitment"
    SCOPE_CREEP        = "scope_creep"
    VELOCITY_DROP      = "velocity_drop"
    BLOCKER_RECURRENCE = "blocker_recurrence"
    SKILL_GAP          = "skill_gap"


class PatternStatus(enum.Enum):
    ACTIVE   = "active"
    RESOLVED = "resolved"


class Retrospective(Base):
    __tablename__ = "retrospectives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sprint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), nullable=False, unique=True)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    went_well: Mapped[list | None] = mapped_column(_JSONB_OR_JSON, nullable=True)
    went_poorly: Mapped[list | None] = mapped_column(_JSONB_OR_JSON, nullable=True)
    action_items: Mapped[list | None] = mapped_column(_JSONB_OR_JSON, nullable=True)
    velocity_summary: Mapped[dict | None] = mapped_column(_JSONB_OR_JSON, nullable=True)


class RetroPattern(Base):
    __tablename__ = "retro_patterns"
    __table_args__ = (
        Index("idx_retro_patterns_team_status", "team_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    pattern_type: Mapped[str] = mapped_column(
        SAEnum(PatternType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_sprint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), nullable=True)
    last_seen_sprint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(PatternStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default="active", server_default="active",
    )
    affected_sprint_names: Mapped[list | None] = mapped_column(_JSONB_OR_JSON, nullable=True)
