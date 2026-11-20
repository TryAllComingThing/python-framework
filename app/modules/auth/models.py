"""Authentication session persistence entity."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LoginSession(Base):
    """Revocable cookie session with hashed credentials."""

    __tablename__ = "sf_login_sessions"
    __table_args__ = (
        Index("ix_sf_login_sessions_expires_at", "expires_at"),
        Index("ix_sf_login_sessions_revoked_at", "revoked_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sf_users.id", ondelete="CASCADE"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_digest: Mapped[str] = mapped_column(String(64))
    auth_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginAttempt(Base):
    """PostgreSQL-backed login throttle bucket."""

    __tablename__ = "sf_login_attempts"
    __table_args__ = (CheckConstraint("failures >= 0", name="ck_sf_login_attempts_failures"),)
    bucket: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
