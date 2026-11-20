from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.core.codes import ErrorCode
from app.core.errors import AppError
from app.modules.auth.dependencies import get_identity
from app.modules.auth.models import LoginSession
from app.modules.auth.rate_limit import account_bucket
from app.modules.auth.security import (
    check_csrf,
    digest,
    hash_password,
    normalize_username,
    username_key,
)
from app.modules.auth.service import authenticate_and_create_session, invalidate_user_authorization
from app.modules.iam.models import Permission, Role, User
from app.modules.iam.policy import Principal, apply_user_scope, require_permission
from tests.helpers import FakeResult, SequenceDB


def _request(*, origin: str | None, token: str | None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if token is not None:
        headers.append((b"x-csrf-token", token.encode()))
    return Request({"type": "http", "method": "POST", "headers": headers, "state": {}})


def test_csrf_requires_trusted_origin_and_matching_token() -> None:
    token = "csrf-token"
    expected = digest(token)
    check_csrf(_request(origin="https://app.test", token=token), expected, ["https://app.test"])

    with pytest.raises(AppError) as missing_origin:
        check_csrf(_request(origin=None, token=token), expected, ["https://app.test"])
    assert missing_origin.value.status_code == 403

    with pytest.raises(AppError):
        check_csrf(
            _request(origin="https://evil.test", token=token), expected, ["https://app.test"]
        )
    with pytest.raises(AppError):
        check_csrf(
            _request(origin="https://app.test", token="wrong"), expected, ["https://app.test"]
        )


def test_username_normalization_and_bucket_share_variant_key() -> None:
    composed = "e\u0301xample"
    expected_username = unicodedata.normalize("NFC", composed).strip()
    actual = normalize_username("  e\u0301XAMPLE  ")
    assert username_key(actual) == username_key(expected_username.upper())
    assert account_bucket(username_key(actual)) == account_bucket(
        username_key(expected_username.upper())
    )
    # PostgreSQL lower() does not expand ß to ss; casefold() would diverge.
    assert account_bucket(username_key("Straße")) != account_bucket(username_key("STRASSE"))


async def test_login_lookup_uses_postgresql_lower_on_both_sides() -> None:
    user = User(
        id=4,
        username="Élodie",
        password_hash=hash_password("correct-password"),
        active=True,
        auth_version=1,
        department_id=None,
    )
    db = SequenceDB(
        [
            FakeResult(None),
            FakeResult(None),
            FakeResult(user),
            FakeResult(None),
            FakeResult(None),
        ]
    )

    await authenticate_and_create_session(
        db,  # type: ignore[arg-type]
        username="e\u0301LODIE",
        password="correct-password",
        ip="127.0.0.1",
        request_id="request-id",
    )

    sql = str(db.statements[2].compile(dialect=postgresql.dialect())).lower()
    assert "lower(sf_users.username) = lower(" in sql


def test_require_permission_and_empty_scope_defaults_to_deny() -> None:
    with pytest.raises(AppError):
        require_permission(Principal(1, None, frozenset(), frozenset()), "system:user:list")

    sql = str(apply_user_scope(select(User), Principal(1, None, frozenset(), frozenset()), User))
    assert "false" in sql.lower()


async def test_identity_filters_inactive_roles() -> None:
    active = Role(id=1, name="active", scope="SELF", active=True)
    active.permissions = [Permission(id=1, code="file:upload")]
    inactive = Role(id=2, name="inactive", scope="ALL", active=False)
    inactive.permissions = [Permission(id=2, code="file:delete:all")]
    user = User(
        id=4,
        username="alice",
        password_hash="unused",
        active=True,
        auth_version=3,
        department_id=None,
    )
    user.roles = [active, inactive]
    session = LoginSession(
        id=9,
        user_id=4,
        token_digest="unused",
        csrf_digest="unused",
        auth_version=3,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        revoked_at=None,
    )
    db = SequenceDB([FakeResult(session), FakeResult(user)])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cookie_auth_enabled=True)))

    identity = await get_identity(request, db, "raw-session")  # type: ignore[arg-type]

    assert identity.principal.permissions == frozenset({"file:upload"})
    assert identity.principal.scopes == frozenset({"SELF"})


@pytest.mark.parametrize(("active", "user_auth_version"), [(False, 3), (True, 4)])
async def test_identity_rejects_disabled_or_authorization_stale_sessions(
    active: bool,
    user_auth_version: int,
) -> None:
    user = User(
        id=4,
        username="alice",
        password_hash="unused",
        active=active,
        auth_version=user_auth_version,
        department_id=None,
    )
    user.roles = []
    session = LoginSession(
        id=9,
        user_id=4,
        token_digest="unused",
        csrf_digest="unused",
        auth_version=3,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        revoked_at=None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cookie_auth_enabled=True)))

    with pytest.raises(AppError) as raised:
        await get_identity(
            request,  # type: ignore[arg-type]
            SequenceDB([FakeResult(session), FakeResult(user)]),  # type: ignore[arg-type]
            "raw-session",
        )

    assert raised.value.code == str(ErrorCode.UNAUTHORIZED)


async def test_authorization_invalidation_is_one_audited_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_calls: list[dict[str, object]] = []

    async def audit(*args: object, **kwargs: object) -> None:
        audit_calls.append(kwargs)

    monkeypatch.setattr("app.modules.auth.service.record_audit", audit)
    db = SequenceDB([FakeResult(5), FakeResult()])

    await invalidate_user_authorization(
        db,  # type: ignore[arg-type]
        user_id=5,
        actor_id=1,
        request_id="req-authz",
    )

    assert db.execute_count == 2
    assert db.commit_count == 1
    assert audit_calls[0]["action"] == "auth.authorization_changed"


async def test_cookie_disabled_rejects_identity_before_database_query() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cookie_auth_enabled=False)))
    with pytest.raises(AppError) as raised:
        await get_identity(request, SequenceDB([]), "raw-session")  # type: ignore[arg-type]
    assert raised.value.code == str(ErrorCode.UNAUTHORIZED)
