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
    # No longer unique: an org can have multiple sessions, one per project
    # (see the Project Hub plan). The plain index (kept) is what the now-
    # multi-row lookups need; ordering by created_at picks the right one.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", server_default="in_progress")
    # Collected via an explicit step (not chat-extracted) since it deterministically
    # steers the interview's system prompt — too load-bearing to leave to LLM inference.
    project_purpose: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Explicit tech-stack step (not chat-extracted, same reasoning as project_purpose
    # above): what the founder already knows, or "new" for "I'm new to this". Feeds the
    # roadmap generator's prompt directly (see roadmap_generator._tech_stack_prompt).
    # Distinct from ProjectBrief.tech_constraints, which is chat-extracted free text
    # about hard requirements/integrations, not tool familiarity.
    known_tech_stack: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    tech_experience: Mapped[str | None] = mapped_column(String(20), nullable=True)
    project_brief: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Set when the extraction pass judges the brief complete. Distinct from
    # status == "completed": the user can end the chat before the brief is full.
    brief_complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # True once the assistant has asked "anything else to add?" but before the
    # founder's answer has been processed. The next turn always completes the
    # interview regardless of what they say — see idea_interview.run_interview_turn.
    awaiting_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    github_skipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Set by POST /github/needs-setup: the founder has no GitHub account and no
    # git installed, so the roadmap gets a fixed "Get set up with GitHub"
    # milestone prepended (see services/github_setup_plan). Deliberately
    # distinct from github_skipped_at, which only ever meant "not right now" —
    # sessions that skipped before this existed must not retroactively grow a
    # beginner setup milestone when their roadmap is regenerated.
    github_setup_needed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Which build_plan sub-flow this session took: "chat" or "import". Null
    # until the user picks (see PUT /plan-source in onboarding_v2.py). Once set
    # and its sub-flow has started, it's fixed for the session — no
    # path-switching UI in v1.
    onboarding_path: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Extracted text only, kept for debugging/audit — the original uploaded
    # file is never persisted (see docs/plans/2026-07-20-import-artifacts.md).
    raw_import_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The import-analysis output: {projectName, summary, milestones: [...]}.
    # No accept/reject state persisted — that review state lives client-side
    # until POST /import/apply.
    proposed_roadmap: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    import_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    selected_github_repo_full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repo_select_skipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Set when the founder accepts (or "continue anyway" past) the drafted
    # roadmap in the plan-review step (see POST /plan/confirm). This is the
    # step's completion signal — distinct from status == "completed" (the idea
    # interview ended) and from org.onboarding_completed_at (the whole flow
    # finished). Only meaningful when the plan_review flag is enabled.
    plan_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
        UUID(as_uuid=True), ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["OnboardingSession"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_onboarding_messages_session_seq", "session_id", "seq"),)
