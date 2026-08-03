import enum
import uuid
from datetime import datetime
from sqlalchemy import Enum as SAEnum, String, DateTime, ForeignKey, Boolean, SmallInteger, JSON
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
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    app_role: Mapped[str] = mapped_column(
        SAEnum(AppRole, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        default="developer",
        nullable=False,
        server_default="developer",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    seniority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    domain_strengths: Mapped[str | None] = mapped_column(String, nullable=True)
    skill_ratings: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    meeting_hours_bucket: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Planner lane color. Stores identity ("you are person 3"), not appearance —
    # the hex values live in apps/web/src/styles/tokens.css as --lane-N-*, so
    # retuning the palette for contrast is a CSS change, never a data migration.
    # Assigned sequentially per team; wraps at the palette size.
    color_index: Mapped[int] = mapped_column(
        SmallInteger, default=0, nullable=False, server_default="0"
    )
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Last time this person did something in the product (loaded their roadmap,
    # moved a task, completed one). Fed by src/services/activity.py from every
    # activity source, read by the anti-dormancy re-engagement banner and the
    # dormancy-detection job. Nullable: a fresh account has no activity yet, and
    # the dormancy read COALESCEs to Organization.onboarding_completed_at.
    # See docs/plans/2026-07-20-anti-dormancy-mvp.md.
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    team: Mapped["Team"] = relationship(back_populates="developers")
    velocity_profiles: Mapped[list["DeveloperVelocityProfile"]] = relationship(back_populates="developer")
    sprint_tickets: Mapped[list["SprintTicket"]] = relationship(back_populates="assignee")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="assignee")
