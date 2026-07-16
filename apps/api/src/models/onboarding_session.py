import enum
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Integer, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base


class OnboardingSessionStatus(enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ProjectPurpose(enum.Enum):
    HOBBY = "hobby"
    STARTUP = "startup"
    LEARNING = "learning"


class OnboardingSession(Base):
    """One idea-interview chat session per organization (onboarding v2)."""

    __tablename__ = "onboarding_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), unique=True, index=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", server_default="in_progress")
    # Collected via an explicit step (not chat-extracted) since it deterministically
    # steers the interview's system prompt — too load-bearing to leave to LLM inference.
    project_purpose: Mapped[str | None] = mapped_column(String(20), nullable=True)
    project_brief: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Set when the extraction pass judges the brief complete. Distinct from
    # status == "completed": the user can end the chat before the brief is full.
    brief_complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    github_skipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages: Mapped[list["OnboardingMessage"]] = relationship(
        back_populates="session", order_by="OnboardingMessage.seq"
    )
    project: Mapped["Project | None"] = relationship(back_populates="onboarding_session", uselist=False)


class OnboardingMessage(Base):
    __tablename__ = "onboarding_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_sessions.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["OnboardingSession"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_onboarding_messages_session_seq", "session_id", "seq"),)
