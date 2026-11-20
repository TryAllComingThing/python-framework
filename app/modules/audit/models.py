"""Audit event persistence entity."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    """Append-only event describing a server-side operation."""

    __tablename__ = "sf_audit_events"
    __table_args__ = (
        Index("ix_sf_audit_events_created_at", "created_at"),
        Index("ix_sf_audit_events_actor_id", "actor_id"),
        Index("ix_sf_audit_events_request_id", "request_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("sf_users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(255))
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
