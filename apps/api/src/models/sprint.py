import uuid
import enum
from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, ForeignKey, Float, Boolean, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class SprintStatus(enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    jira_sprint_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    committed_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[SprintStatus] = mapped_column(SAEnum(SprintStatus, values_callable=lambda obj: [e.name for e in obj]), default=SprintStatus.PLANNING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    team: Mapped["Team"] = relationship(back_populates="sprints")
    sprint_tickets: Mapped[list["SprintTicket"]] = relationship(back_populates="sprint")
    sprint_alerts: Mapped[list["SprintAlert"]] = relationship(back_populates="sprint")


class SprintTicket(Base):
    __tablename__ = "sprint_tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sprint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), index=True)
    ticket_id: Mapped[str] = mapped_column(String(100), index=True)  # Jira ticket key/ID
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("developers.id"), nullable=True, index=True)
    estimated_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    slip_cause: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sprint: Mapped["Sprint"] = relationship(back_populates="sprint_tickets")
    assignee: Mapped["Developer | None"] = relationship(back_populates="sprint_tickets")
