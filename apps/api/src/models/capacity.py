import uuid
from datetime import datetime
from sqlalchemy import Float, Text, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class DeveloperCapacityOverride(Base):
    __tablename__ = "developer_capacity_overrides"
    __table_args__ = (
        UniqueConstraint("developer_id", "sprint_id", name="uq_dev_capacity_sprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    developer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True)
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id", ondelete="CASCADE"), nullable=True)
    capacity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pto_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
