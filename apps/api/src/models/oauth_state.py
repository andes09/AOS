from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255))
    org_id: Mapped[str] = mapped_column(String(255))
    return_to: Mapped[str] = mapped_column(String(255), server_default="/onboarding")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
