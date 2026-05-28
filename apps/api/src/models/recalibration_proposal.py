"""Recalibration proposal model (M8c, Initiative A Wave 5).

The override analyzer emits proposals to lower a developer's skill rating or
reclassify an identifier's skill when repeated lead overrides indicate a
systematic miscalibration. Each row is also its own audit record: when a lead
approves or dismisses, `decided_at` + `decided_by` capture who/when, and
`evidence` JSONB stores the SprintPlanOverride ids that triggered it. No
separate audit table is needed.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base

_JSONB_OR_JSON = JSON().with_variant(JSONB(), "postgresql")


class ProposalKind(enum.Enum):
    """Kind of recalibration suggested.

    Stored as VARCHAR(20) (no native pg enum) so values can grow.
    """
    SKILL_RATING     = "skill_rating"
    IDENTIFIER_SKILL = "identifier_skill"


class ProposalStatus(enum.Enum):
    PENDING   = "pending"
    APPROVED  = "approved"
    DISMISSED = "dismissed"


class RecalibrationProposal(Base):
    __tablename__ = "recalibration_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    developer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developers.id", ondelete="CASCADE"), nullable=True
    )
    identifier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("team_identifiers.id", ondelete="CASCADE"), nullable=True
    )
    skill: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_skill: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence: Mapped[list] = mapped_column(
        _JSONB_OR_JSON, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(15), nullable=False, default="pending", server_default="pending"
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
