import enum
import uuid
from datetime import datetime
from sqlalchemy import Enum as SAEnum, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class AppRole(enum.Enum):
    DEVELOPER = "developer"
    LEAD      = "lead"
    EXEC      = "exec"
    ADMIN     = "admin"


class TeamMember(Base):
    """Jira-sourced team member, distinct from Clerk-registered Developer users."""
    __tablename__ = "team_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    jira_account_id: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    team: Mapped["Team"] = relationship(back_populates="team_members")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="assignee")


class Developer(Base):
    __tablename__ = "developers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    clerk_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    team: Mapped["Team"] = relationship(back_populates="developers")
    velocity_profiles: Mapped[list["DeveloperVelocityProfile"]] = relationship(back_populates="developer")
    sprint_tickets: Mapped[list["SprintTicket"]] = relationship(back_populates="assignee")
