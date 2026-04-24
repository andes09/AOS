import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Float, Enum as SAEnum, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.database import Base


class TicketStatus(enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), nullable=True, index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("team_members.id"), nullable=True, index=True)
    jira_issue_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    jira_issue_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(SAEnum(TicketStatus, values_callable=lambda obj: [e.name for e in obj]), default=TicketStatus.TODO)
    ticket_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    story_points_estimated: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_estimate_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    components: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_carryover: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    jira_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sprint: Mapped["Sprint"] = relationship()
    team: Mapped["Team"] = relationship()
    assignee: Mapped["TeamMember | None"] = relationship(back_populates="tickets")
