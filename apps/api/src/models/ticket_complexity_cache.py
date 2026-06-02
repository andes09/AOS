from datetime import datetime
from sqlalchemy import String, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class TicketComplexityCache(Base):
    __tablename__ = "ticket_complexity_cache"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    complexity_json: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
