"""Session validation and IAM-backed authorization dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.codes import ErrorCode
from app.core.database import get_session
from app.core.errors import AppError
from app.modules.auth.models import LoginSession
from app.modules.auth.security import SESSION_COOKIE_NAME, check_csrf, digest
from app.modules.iam.grants import custom_grants, descendants
from app.modules.iam.models import Role, User
from app.modules.iam.policy import Principal, require_permission

session_cookie = APIKeyCookie(name=SESSION_COOKIE_NAME, auto_error=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Identity:
    """Authenticated user, validated session and effective IAM grants."""

    user: User
    session: LoginSession
    principal: Principal


async def get_identity(
    request: Request,
    db: SessionDep,
    session_cookie_value: Annotated[str | None, Security(session_cookie)],
) -> Identity:
    """Load server-side grants; disabled roles never grant permissions or scopes.

    Cookies are rejected entirely when cookie authentication is disabled, even
    if a caller manually supplies ``sf_session``.
    """
    if not request.app.state.cookie_auth_enabled:
        raise AppError(ErrorCode.UNAUTHORIZED, 401)
    raw = session_cookie_value or request.cookies.get(SESSION_COOKIE_NAME, "")
    if not raw:
        raise AppError(ErrorCode.UNAUTHORIZED, 401)
    record = (
        await db.execute(select(LoginSession).where(LoginSession.token_digest == digest(raw)))
    ).scalar_one_or_none()
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at <= datetime.now(timezone.utc)
    ):
        raise AppError(ErrorCode.UNAUTHORIZED, 401)
    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.id == record.user_id)
        )
    ).scalar_one_or_none()
    if user is None or not user.active or user.auth_version != record.auth_version:
        raise AppError(ErrorCode.UNAUTHORIZED, 401)

    active_roles = [role for role in user.roles if role.active]
    permissions = frozenset(
        permission.code for role in active_roles for permission in role.permissions
    )
    scopes = frozenset(role.scope for role in active_roles)
    subtree = (
        await descendants(db, user.department_id)
        if "DEPARTMENT_AND_CHILDREN" in scopes
        else frozenset()
    )
    custom = (
        await custom_grants(
            db,
            [role.id for role in active_roles if role.scope == "CUSTOM"],
        )
        if "CUSTOM" in scopes
        else frozenset()
    )
    return Identity(
        user,
        record,
        Principal(user.id, user.department_id, permissions, scopes, subtree, custom),
    )


IdentityDep = Annotated[Identity, Depends(get_identity)]


def permission(code: str) -> Callable[[Identity], Awaitable[Identity]]:
    """Construct an authorization dependency for one explicit permission code."""

    async def guard(identity: IdentityDep) -> Identity:
        require_permission(identity.principal, code)
        return identity

    return guard


async def csrf_identity(
    request: Request,
    identity: IdentityDep,
) -> Identity:
    """Require a valid CSRF token for cookie-authenticated state-changing calls.

    The header is declared as required by each write operation's ``openapi_extra``
    while runtime validation remains in :func:`check_csrf`, so missing and invalid
    tokens share the same non-oracle 403 response.
    """
    check_csrf(request, identity.session.csrf_digest, request.app.state.csrf_origins)
    return identity
