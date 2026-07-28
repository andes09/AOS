import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_org_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    encrypted_anthropic_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_managed_key: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # NULL = unlimited. Counts all projects regardless of status (see
    # routers/projects.py) — archiving is a visibility flag, not a
    # resource-freeing operation, so it must not be a loophole around the cap.
    max_projects: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Monotonic counter behind Task.short_id (e.g. "AOS-142"). Incremented
    # atomically via UPDATE ... RETURNING (see src/services/task_ids.py) so
    # concurrent task creation for the same org never collides on a number.
    next_task_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teams: Mapped[list["Team"]] = relationship(back_populates="organization")
    github_connections: Mapped[list["GithubConnection"]] = relationship(back_populates="organization")
