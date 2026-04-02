import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Index
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class DependencyType(enum.Enum):
    BLOCKS           = "blocks"
    IS_BLOCKED_BY    = "is_blocked_by"
    EXTERNAL_SERVICE = "external_service"
    CROSS_TEAM       = "cross_team"


class RiskLevel(enum.Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        Index("idx_dep_team_resolved", "team_id", "resolved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    ticket_key: Mapped[str] = mapped_column(String(50), nullable=False)
    ticket_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_by_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dependency_type: Mapped[str] = mapped_column(
        SAEnum(DependencyType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    risk_level: Mapped[str] = mapped_column(
        SAEnum(RiskLevel, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
