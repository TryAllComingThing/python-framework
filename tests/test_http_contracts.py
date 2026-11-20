from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.common.pagination import Page
from app.core.codes import ErrorCode
from app.core.config import Settings
from app.core.database import get_session
from app.core.errors import AppError
from app.main import create_app
from app.modules.auth.dependencies import get_identity
from app.modules.auth.security import digest
from app.modules.auth.service import SessionCredentials
from app.modules.iam.policy import Principal
from app.modules.iam.schemas import UserSummaryResponse


async def _fake_session() -> AsyncIterator[object]:
    yield SimpleNamespace()


def _app(tmp_path: Path, *, cookie_auth_enabled: bool = True):
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="staging",
        file_storage_root=str(tmp_path / "uploads"),
        cors_origins=["https://app.test"],
        csrf_origins=["https://app.test"],
        cookie_auth_enabled=cookie_auth_enabled,
    )
    app = create_app(settings)
    app.dependency_overrides[get_session] = _fake_session
    return app


def _identity(*permissions: str) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=7, username="alice", auth_version=1),
        session=SimpleNamespace(id=11, csrf_digest=digest("csrf-token")),
        principal=Principal(
            user_id=7,
            department_id=None,
            permissions=frozenset(permissions),
            scopes=frozenset({"SELF"}),
            department_ids=frozenset(),
            custom_department_ids=frozenset(),
        ),
    )


def test_login_requires_origin_and_sets_secure_cookie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def credentials(*args: object, **kwargs: object) -> SessionCredentials:
        return SessionCredentials(
            user_id=7, session_token="session-secret", csrf_token="csrf-token"
        )

    monkeypatch.setattr(
        "app.modules.auth.router.authenticate_and_create_session",
        credentials,
    )
    with TestClient(_app(tmp_path)) as client:
        missing = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "password"},
        )
        valid = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://app.test"},
            json={"username": "alice", "password": "password"},
        )

    assert missing.status_code == 403
    assert missing.json()["code"] == str(ErrorCode.FORBIDDEN)
    assert valid.status_code == 200
    assert valid.json()["data"] == {"csrf_token": "csrf-token", "user_id": 7}
    cookie = valid.headers["set-cookie"].lower()
    assert "sf_session=session-secret" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=" in cookie


def test_missing_session_and_throttled_login_expose_protocol_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def throttled(*args: object, **kwargs: object) -> SessionCredentials:
        raise AppError(ErrorCode.TOO_MANY_REQUESTS, 429)

    monkeypatch.setattr("app.modules.auth.router.authenticate_and_create_session", throttled)
    with TestClient(_app(tmp_path)) as client:
        unauthorized = client.get("/api/v1/auth/me")
        limited = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://app.test"},
            json={"username": "alice", "password": "password"},
        )

    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"].startswith("Session")
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_logout_rejects_missing_csrf_before_service_write(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_identity] = lambda: _identity()
    with TestClient(app) as client:
        missing_origin = client.post("/api/v1/auth/logout")
        missing_token = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://app.test"},
        )

    assert missing_origin.status_code == 403
    assert missing_token.status_code == 403


def test_logout_success_revokes_session_and_expires_cookie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revoked: list[int] = []

    async def revoke(*args: object, **kwargs: object) -> None:
        revoked.append(cast(SimpleNamespace, kwargs["session"]).id)

    monkeypatch.setattr("app.modules.auth.router.revoke_session", revoke)
    app = _app(tmp_path)
    app.dependency_overrides[get_identity] = lambda: _identity()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://app.test", "X-CSRF-Token": "csrf-token"},
        )

    assert response.status_code == 200
    assert response.json()["data"] == {"logged_out": True}
    assert revoked == [11]
    assert 'sf_session=""' in response.headers["set-cookie"].lower()


def test_rotate_success_sets_replacement_cookie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rotate(*args: object, **kwargs: object) -> tuple[str, str]:
        return "replacement-session", "replacement-csrf"

    monkeypatch.setattr("app.modules.auth.router.rotate_session_credential", rotate)
    app = _app(tmp_path)
    app.dependency_overrides[get_identity] = lambda: _identity()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/rotate",
            headers={"Origin": "https://app.test", "X-CSRF-Token": "csrf-token"},
        )

    assert response.status_code == 200
    assert response.json()["data"] == {"csrf_token": "replacement-csrf"}
    assert "sf_session=replacement-session" in response.headers["set-cookie"].lower()


def test_health_ready_reports_database_probe_success(tmp_path: Path) -> None:
    async def execute(*args: object, **kwargs: object) -> None:
        return None

    class FakeDatabase:
        @asynccontextmanager
        async def sessions(self) -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(execute=execute)

        async def close(self) -> None:
            return None

    app = _app(tmp_path, cookie_auth_enabled=False)
    with TestClient(app) as client:
        app.state.db = FakeDatabase()
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_iam_http_shapes_and_page_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def list_users(*args: object, **kwargs: object) -> list[UserSummaryResponse]:
        return [UserSummaryResponse(id=7, username="alice")]

    async def page_users(*args: object, **kwargs: object) -> Page[UserSummaryResponse]:
        return Page(
            items=[UserSummaryResponse(id=7, username="alice")],
            total=1,
            page=1,
            page_size=20,
        )

    monkeypatch.setattr("app.modules.iam.router.list_user_summaries", list_users)
    monkeypatch.setattr("app.modules.iam.router.page_user_summaries", page_users)
    app = _app(tmp_path, cookie_auth_enabled=False)
    app.dependency_overrides[get_identity] = lambda: _identity("system:user:list")
    with TestClient(app) as client:
        v1 = client.get("/api/v1/iam/users")
        v2 = client.get("/api/v2/iam/users")
        invalid = client.get("/api/v2/iam/users", params={"page": 0})

    assert v1.status_code == 200
    assert isinstance(v1.json()["data"], list)
    assert v1.headers["deprecation"] == "true"
    assert v2.status_code == 200
    assert isinstance(v2.json()["data"], dict)
    assert v2.json()["data"]["items"] == [{"id": 7, "username": "alice"}]
    assert invalid.status_code == 422
    assert invalid.json()["code"] == str(ErrorCode.VALIDATION_ERROR)
