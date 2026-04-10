import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class TeamAccessGrant(Base):
    __tablename__ = "team_access_grants"
    __table_args__ = (
        UniqueConstraint("developer_id", "team_id", name="uq_team_access_grant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    developer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
