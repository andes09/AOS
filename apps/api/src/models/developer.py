import enum
import uuid
from datetime import datetime
from sqlalchemy import Enum as SAEnum, String, DateTime, ForeignKey, Boolean, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base


class AppRole(enum.Enum):
    DEVELOPER = "developer"
    LEAD      = "lead"
    EXEC      = "exec"
    ADMIN     = "admin"


class Developer(Base):
    __tablename__ = "developers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    clerk_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Jira account ID — set when this developer is matched/synced from Jira.
    # Partial unique index (team_id, jira_account_id) WHERE jira_account_id IS NOT NULL
    # is enforced in the DB; NULLs here mean "no Jira account linked yet".
    jira_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    app_role: Mapped[str] = mapped_column(
        SAEnum(AppRole, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        default="developer",
        nullable=False,
        server_default="developer",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    seniority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    capacity_hours_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    domain_strengths: Mapped[str | None] = mapped_column(String, nullable=True)
    skill_ratings: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    meeting_hours_bucket: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    team: Mapped["Team"] = relationship(back_populates="developers")
    velocity_profiles: Mapped[list["DeveloperVelocityProfile"]] = relationship(back_populates="developer")
    sprint_tickets: Mapped[list["SprintTicket"]] = relationship(back_populates="assignee")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="assignee")
