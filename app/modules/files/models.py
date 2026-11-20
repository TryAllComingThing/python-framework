"""Authorized file metadata. The storage key is never a public identifier."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FileRecord(Base):
    """Owned file metadata; the private object key must never appear in API output."""

    __tablename__ = "sf_file_records"
    __table_args__ = (
        CheckConstraint("size > 0", name="ck_sf_file_records_size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_sf_file_records_sha256"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("sf_users.id", ondelete="RESTRICT"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileCleanupJob(Base):
    """Durable deletion intent; object key must not be exposed by public APIs."""

    __tablename__ = "sf_file_cleanup_jobs"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_sf_file_cleanup_jobs_attempts"),
        Index("ix_sf_file_cleanup_jobs_lease_created", "lease_until", "created_at"),
        Index("ix_sf_file_cleanup_jobs_created", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    object_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    file_id: Mapped[int | None] = mapped_column(nullable=True)
    reason: Mapped[str] = mapped_column(
        String(32), nullable=False, default="delete", server_default="delete"
    )
    # Active PostgreSQL lease claim columns used by the explicit cleanup operator CLI.
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
