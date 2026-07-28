import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class GithubActivityEvent(Base):
    """
    Append-only log of GitHub activity (pushes, PR opens/merges/closes) that
    was inspected for task auto-complete matching — fed by both the app-level
    webhook receiver (near-real-time) and the reconciliation sweep (safety
    net for missed deliveries).

    `UNIQUE (organization_id, repo_full_name, event_type, external_id)` is
    the idempotency mechanism: whichever path (webhook or reconciliation)
    sees a given commit/PR action first "wins" the insert, and the other is a
    harmless no-op. `occurred_at` doubles as the reconciliation sweep's
    per-repo cursor via `MAX(occurred_at)` — see
    src/integrations/github/events.py — so there's no separate sync-state
    table to keep consistent.
    """

    __tablename__ = "github_activity_events"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "repo_full_name", "event_type", "external_id",
            name="uq_github_activity_events_org_repo_type_external_id",
        ),
        Index("ix_github_activity_events_org_repo_occurred_at", "organization_id", "repo_full_name", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    repo_full_name: Mapped[str] = mapped_column(String(255))
    # "push" | "pr_opened" | "pr_merged" | "pr_closed"
    event_type: Mapped[str] = mapped_column(String(20))
    # Commit SHA for "push"; "pr-{number}-{action}" for pull_request events.
    external_id: Mapped[str] = mapped_column(String(255))
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_or_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    matched_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    matched_task: Mapped["Task | None"] = relationship()
