"""PostgreSQL-backed account and IP login throttling, no Redis required."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import LoginAttempt


def account_bucket(canonical_username_key: str) -> str:
    """Build a non-reversible bucket from an already canonical username key."""
    return hashlib.sha256(("account|" + canonical_username_key).encode()).hexdigest()


def ip_bucket(ip: str) -> str:
    """Build a non-reversible client-IP throttle bucket."""
    return hashlib.sha256(("ip|" + ip).encode()).hexdigest()


async def is_locked(
    db: AsyncSession,
    bucket: str,
    now: datetime | None = None,
) -> bool:
    """Return whether a throttle bucket is currently locked."""
    current = now or datetime.now(timezone.utc)
    value = (
        await db.execute(select(LoginAttempt.locked_until).where(LoginAttempt.bucket == bucket))
    ).scalar_one_or_none()
    return value is not None and value > current


async def register_failure(
    db: AsyncSession,
    bucket: str,
    now: datetime | None = None,
    threshold: int = 5,
    window_seconds: int = 900,
) -> None:
    """Increment a failure bucket atomically inside the caller transaction."""
    current = now or datetime.now(timezone.utc)
    recent = LoginAttempt.window_start > current - timedelta(seconds=window_seconds)
    next_count = case((recent, LoginAttempt.failures + 1), else_=1)
    statement = (
        insert(LoginAttempt)
        .values(bucket=bucket, failures=1, window_start=current, locked_until=None)
        .on_conflict_do_update(
            index_elements=[LoginAttempt.bucket],
            set_={
                "failures": next_count,
                "window_start": case(
                    (recent, LoginAttempt.window_start),
                    else_=current,
                ),
                "locked_until": case(
                    (
                        next_count >= threshold,
                        current + timedelta(seconds=window_seconds),
                    ),
                    else_=None,
                ),
            },
        )
    )
    await db.execute(statement)


async def clear_failures(db: AsyncSession, bucket: str) -> None:
    """Clear one failure bucket inside the caller transaction."""
    await db.execute(delete(LoginAttempt).where(LoginAttempt.bucket == bucket))
