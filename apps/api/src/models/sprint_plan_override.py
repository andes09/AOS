"""Sprint plan override capture model (M8a, Initiative A Wave 4).

Each lead-driven assignment edit (reassign / remove / add) on a sprint plan
writes one row here. SA-15's plan-quality telemetry aggregates these rows
into `Sprint.plan_override_rate` and `Sprint.plan_overrides_by_reason`.

Action and reason are stored as VARCHAR (no native pg enum) so values can
evolve without an enum migration. The Python enums below document the
allowed values for callers / pydantic schemas.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class OverrideAction(enum.Enum):
    REASSIGN = "reassign"
    REMOVE   = "remove"
    ADD      = "add"


class OverrideReason(enum.Enum):
    SKILL_FIT       = "skill_fit"
    CAPACITY        = "capacity"
    MENTORSHIP      = "mentorship"
    PTO             = "pto"
    PRIORITY_CHANGE = "priority_change"
    OTHER           = "other"


class SprintPlanOverride(Base):
    __tablename__ = "sprint_plan_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sprints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    original_developer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developers.id", ondelete="SET NULL"), nullable=True
    )
    new_developer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developers.id", ondelete="SET NULL"), nullable=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `created_by` stores the Developer.id (UUID) of the lead making the edit.
    # We resolve the Clerk user id -> Developer row at write time. NULL when
    # the actor cannot be resolved (e.g. system / backfill).
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
