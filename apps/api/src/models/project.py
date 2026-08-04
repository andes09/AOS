import enum
import uuid
from datetime import datetime
from sqlalchemy import JSON, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from src.database import Base


class ProjectStatus(enum.Enum):
    ACTIVE = "active"
    FINISHED = "finished"
    ARCHIVED = "archived"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id"), index=True
    )
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_sessions.id"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Genuinely plain string column — ProjectStatus is a value source only, not
    # wrapped in SQLAlchemy's Enum type. That type reloads as the enum *member*
    # (not its string value) once an instance is re-fetched from the DB, which
    # broke routers/projects.py's plain Python string comparisons against
    # _ALLOWED_TRANSITIONS after a round-trip. A plain String avoids that trap.
    # Manual transition only — never derived from task completion.
    status: Mapped[str] = mapped_column(
        String(20), default=ProjectStatus.ACTIVE.value, server_default="active",
    )
    # Set from onboarding's repo-select step (PUT /repo), either immediately
    # (import path, once the Project already exists) or copied on at creation
    # time by roadmap_generator.generate_roadmap (chat path).
    github_repo_full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Generation-fidelity telemetry for the task dependency graph: how much of
    # the `dependsOn` graph the planner proposed actually survived validation.
    # Written by whichever path last built the DAG (see
    # roadmap_shapes.record_plan_quality); read back — and turned into rates and
    # DAG-shape metrics — by services/plan_quality.py. Raw counts only, so this
    # column stays a plain fact about the build rather than a cached derivation.
    # NULL for a project whose roadmap predates this column.
    plan_quality: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team: Mapped["Team"] = relationship(back_populates="projects")
    onboarding_session: Mapped["OnboardingSession"] = relationship(back_populates="project")
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Milestone.sort_order",
    )
