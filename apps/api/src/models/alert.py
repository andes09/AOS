import uuid
import enum
from datetime import datetime
from sqlalchemy import DateTime, Boolean, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class AlertType(enum.Enum):
    stalled_ticket = "stalled_ticket"
    over_capacity = "over_capacity"
    dependency_risk = "dependency_risk"
    spillover_prediction = "spillover_prediction"


class SprintAlert(Base):
    __tablename__ = "sprint_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sprint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    type: Mapped[AlertType] = mapped_column(SAEnum(AlertType))
    description: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sprint: Mapped["Sprint"] = relationship(back_populates="sprint_alerts")
    team: Mapped["Team"] = relationship(back_populates="sprint_alerts")
