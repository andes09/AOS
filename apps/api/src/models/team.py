import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    jira_board_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    jira_project_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sprint_length_days: Mapped[int] = mapped_column(Integer, default=14)
    jira_import_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    jira_import_sprints_imported: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meeting_overhead_pct: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    size_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    methodology: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tech_stack: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_setup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="teams")
    developers: Mapped[list["Developer"]] = relationship(back_populates="team")
    sprints: Mapped[list["Sprint"]] = relationship(back_populates="team")
    sprint_alerts: Mapped[list["SprintAlert"]] = relationship(back_populates="team")
    projects: Mapped[list["Project"]] = relationship(back_populates="team")
