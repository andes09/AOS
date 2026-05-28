"""TicketRevision audit ORM (Initiative B, SB-2).

One row per ticket per commit through the inline-refinement flow. See
`alembic/versions/0021_ticket_revisions.py` for column semantics.

Uses the `JSON().with_variant(JSONB(), "postgresql")` pattern so the model
loads cleanly under SQLite-backed test fixtures while still landing as
native JSONB in Postgres.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


_JSONB_OR_JSON = JSON().with_variant(JSONB(), "postgresql")


class TicketRevision(Base):
    __tablename__ = "ticket_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # FK is nullable + ON DELETE SET NULL because the new inline-refinement
    # flow can act on Jira keys we have not yet ingested as a `tickets` row.
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Always populated — Jira issue key (e.g. "PROJ-123"). Indexed alongside
    # team_id for the audit-row lookup path.
    ticket_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # What Scope Cop proposed (title, description, acceptance_criteria[], story_points, ...).
    suggested_revision: Mapped[dict] = mapped_column(
        _JSONB_OR_JSON, nullable=False, default=dict
    )
    # What the user actually pushed (may differ from suggested if they edited).
    applied_revision: Mapped[dict] = mapped_column(
        _JSONB_OR_JSON, nullable=False, default=dict
    )
    # Pre-edit Jira snapshot for future rollback — title, description, AC,
    # story points, assignee, sprint id.
    original_jira_state: Mapped[dict] = mapped_column(
        _JSONB_OR_JSON, nullable=False, default=dict
    )

    applied_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    # `applied_by` stores a UUID (Developer.id when resolvable) — no FK, no
    # `users` table in this codebase. Matches `sprint_plan_overrides.created_by`.
    applied_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
