import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.database import Base


class AIUsageEvent(Base):
    """
    Append-only log of AI generation cost, one row per `record_generation_cost`
    call (see src/services/cost_tracker.py). Feeds the platform admin
    dashboard's cost charts/rollups — never read or written by the generation
    paths themselves, only by the cost tracker's own short-lived session, so a
    failure here can never break the generation it's logging.

    `cost_usd` is NUMERIC(12,6), not float, since these values get summed
    across potentially many rows for dashboard totals and float drift is
    unacceptable for a cost figure.
    """

    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_events_org_created_at", "organization_id", "created_at"),
        Index("ix_ai_usage_events_created_at", "created_at"),
        Index("ix_ai_usage_events_provider_created_at", "provider", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id"), nullable=True, index=True
    )
    # 'anthropic' | 'groq'
    provider: Mapped[str] = mapped_column(String(20))
    # sprint_plan / roadmap_generate / roadmap_regenerate /
    # roadmap_regenerate_milestone / idea_interview / roadmap_adjust /
    # roadmap_extend_day / artifact_import_analyze / ...
    operation: Mapped[str] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6))
    # Catch-all for existing free-form kwargs (session_id, milestone_id, ...).
    context: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
