"""Authentication application service. Owns database writes and audit transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import func, literal, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.codes import ErrorCode
from app.core.errors import AppError
from app.modules.audit.service import record_audit
from app.modules.auth.models import LoginSession
from app.modules.auth.rate_limit import (
    account_bucket,
    clear_failures,
    ip_bucket,
    is_locked,
    register_failure,
)
from app.modules.auth.security import (
    digest,
    new_secret,
    normalize_username,
    username_key,
    verify_login_password,
)
from app.modules.iam.models import User


@dataclass(frozen=True)
class SessionCredentials:
    """Raw session credentials returned once by the login service."""

    user_id: int
    session_token: str
    csrf_token: str


async def authenticate_and_create_session(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    ip: str,
    request_id: str,
    session_ttl_seconds: int = 8 * 60 * 60,
) -> SessionCredentials:
    """Verify credentials and create an auditable session in one transaction.

    Locked, failed and successful attempts commit throttle/audit writes together.
    Unexpected database failures roll back and propagate.
    """
    try:
        normalized = normalize_username(username)
        lookup_username: str | None = normalized
        normalized_key = username_key(normalized)
    except ValueError:
        # Keep authentication failure behavior uniform for malformed account input.
        # Do not send invalid control characters or overlong values to PostgreSQL.
        normalized = username.strip()[:100]
        lookup_username = None
        normalized_key = normalized.lower()
    account, address = account_bucket(normalized_key), ip_bucket(ip)
    if await is_locked(db, account) or await is_locked(db, address):
        try:
            await record_audit(
                db,
                actor_id=None,
                action="auth.login_throttled",
                target=f"account:{account}",
                request_id=request_id,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        raise AppError(
            ErrorCode.TOO_MANY_REQUESTS,
            429,
            headers={"Retry-After": "900"},
        )

    user: User | None = None
    if lookup_username is not None:
        # Let PostgreSQL compute both sides so Unicode/collation semantics match
        # the expression index and the database uniqueness constraint exactly.
        user = (
            await db.execute(
                select(User).where(
                    func.lower(User.username) == func.lower(literal(lookup_username))
                )
            )
        ).scalar_one_or_none()
    password_valid = verify_login_password(
        user.password_hash if user is not None else None,
        password,
    )
    if user is None or not user.active or not password_valid:
        try:
            await register_failure(db, account, threshold=5)
            await register_failure(db, address, threshold=20)
            await record_audit(
                db,
                actor_id=user.id if user is not None else None,
                action="auth.login_failed",
                target=f"account:{account}",
                request_id=request_id,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        raise AppError(ErrorCode.UNAUTHORIZED, 401)
    try:
        await clear_failures(db, account)
        raw, csrf = new_secret(), new_secret()
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        session = LoginSession(
            user_id=user.id,
            token_digest=digest(raw),
            csrf_digest=digest(csrf),
            auth_version=user.auth_version,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=session_ttl_seconds),
        )
        db.add(session)
        await record_audit(
            db,
            actor_id=user.id,
            action="auth.login",
            target=str(user.id),
            request_id=request_id,
        )
        await db.commit()
        return SessionCredentials(user.id, raw, csrf)
    except Exception:
        await db.rollback()
        raise


async def revoke_session(
    db: AsyncSession,
    *,
    session: LoginSession,
    actor_id: int,
    request_id: str,
) -> None:
    """Revoke one active session and commit its audit record."""
    try:
        session.revoked_at = datetime.now(timezone.utc)
        await record_audit(
            db,
            actor_id=actor_id,
            action="auth.logout",
            target=str(session.id),
            request_id=request_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def rotate_session_credential(
    db: AsyncSession,
    *,
    session: LoginSession,
    actor_id: int,
    auth_version: int,
    request_id: str = "unknown",
) -> tuple[str, str]:
    """Rotate a credential while preserving transactional audit semantics."""
    raw, csrf = new_secret(), new_secret()
    try:
        result = cast(
            CursorResult[tuple[object]],
            await db.execute(
                update(LoginSession)
                .where(
                    LoginSession.id == session.id,
                    LoginSession.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(timezone.utc))
            ),
        )
        if result.rowcount != 1:
            raise AppError(ErrorCode.UNAUTHORIZED, 401)
        db.add(
            LoginSession(
                user_id=actor_id,
                token_digest=digest(raw),
                csrf_digest=digest(csrf),
                auth_version=auth_version,
                expires_at=session.expires_at,
            )
        )
        await record_audit(
            db,
            actor_id=actor_id,
            action="auth.session_rotated",
            target=str(session.id),
            request_id=request_id,
        )
        await db.commit()
        return raw, csrf
    except Exception:
        await db.rollback()
        raise


async def invalidate_user_authorization(
    db: AsyncSession,
    *,
    user_id: int,
    actor_id: int,
    request_id: str,
) -> None:
    """Bump auth version and revoke active sessions in one audited transaction.

    Callers must invoke this after role, permission or account activation changes.
    A concurrent request that already loaded old grants can complete; subsequent
    requests fail the session's auth-version check.
    """
    try:
        result = cast(
            CursorResult[tuple[object]],
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(auth_version=User.auth_version + 1)
                .returning(User.id)
            ),
        )
        if result.scalar_one_or_none() is None:
            raise AppError(ErrorCode.NOT_FOUND, 404)
        await db.execute(
            update(LoginSession)
            .where(
                LoginSession.user_id == user_id,
                LoginSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await record_audit(
            db,
            actor_id=actor_id,
            action="auth.authorization_changed",
            target=str(user_id),
            request_id=request_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
