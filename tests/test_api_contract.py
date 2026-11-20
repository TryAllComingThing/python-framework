from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import Response

from app.common.openapi import error_responses
from app.common.pagination import PageParams
from app.core.config import Settings
from app.main import create_app
from app.modules.auth.router import _delete_session_cookie, _set_session_cookie


def _test_app(
    tmp_path: Path,
    *,
    cors_origins: list[str] | None = None,
    csrf_origins: list[str] | None = None,
    cookie_auth_enabled: bool = False,
    max_request_bytes: int = 10 * 1024 * 1024,
    log_level: str = "INFO",
):
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        file_storage_root=str(tmp_path / "uploads"),
        cors_origins=cors_origins or [],
        csrf_origins=csrf_origins or [],
        cookie_auth_enabled=cookie_auth_enabled,
        max_request_bytes=max_request_bytes,
        log_level=log_level,
    )
    return create_app(settings)


def test_configured_log_level_is_applied(tmp_path: Path) -> None:
    logger = logging.getLogger("python_framework")
    previous_level = logger.level
    try:
        with TestClient(_test_app(tmp_path, log_level="DEBUG")):
            pass
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(previous_level)


def test_common_protocol_error_statuses_have_openapi_metadata() -> None:
    declared = error_responses(405, 406, 412, 428)
    assert set(declared) == {405, 406, 412, 428}


def test_unknown_route_and_method_use_unified_error_envelope(tmp_path: Path) -> None:
    with TestClient(_test_app(tmp_path)) as client:
        missing = client.get("/api/v1/does-not-exist")
        wrong_method = client.post("/health/live")

    assert missing.status_code == 404
    assert set(missing.json()) == {"code", "message", "request_id", "details"}
    assert missing.json()["code"] == "COMMON.NOT_FOUND"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["code"] == "COMMON.METHOD_NOT_ALLOWED"
    assert wrong_method.headers["allow"] == "GET"


def test_declared_content_length_limit_returns_413(tmp_path: Path) -> None:
    with TestClient(_test_app(tmp_path, max_request_bytes=1024)) as client:
        response = client.post("/health/live", content=b"x" * 2048)
    assert response.status_code == 413
    assert response.json()["code"] == "COMMON.PAYLOAD_TOO_LARGE"


def test_cors_preflight_allows_file_range_and_conditional_headers(tmp_path: Path) -> None:
    app = _test_app(
        tmp_path,
        cors_origins=["https://app.test"],
        csrf_origins=["https://app.test"],
    )
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/files/1",
            headers={
                "Origin": "https://app.test",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "x-csrf-token, range, if-none-match",
            },
        )
        actual = client.get("/health/live", headers={"Origin": "https://app.test"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.test"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "range" in allowed
    assert "if-none-match" in allowed
    exposed = actual.headers["access-control-expose-headers"].lower()
    assert "etag" in exposed
    assert "content-range" in exposed


def test_settings_normalize_and_deduplicate_origins() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        cors_origins=[
            "HTTPS://App.Test:443",
            "https://app.test/",
            "http://127.0.0.1:80",
        ],
        csrf_origins=["https://app.test"],
    )
    assert settings.cors_origins == ["https://app.test", "http://127.0.0.1"]
    assert settings.csrf_origins == ["https://app.test"]


def test_cookie_auth_requires_csrf_origins_to_be_a_cors_subset(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="subset of CORS origins"):
        _test_app(
            tmp_path,
            cors_origins=["https://app.test"],
            csrf_origins=["https://csrf.test"],
            cookie_auth_enabled=True,
        )

    app = _test_app(
        tmp_path,
        cors_origins=["https://app.test"],
        csrf_origins=["https://app.test"],
        cookie_auth_enabled=True,
    )
    assert app.state.csrf_origins == ["https://app.test"]


def test_cookie_auth_csrf_origin_gate_covers_empty_and_disabled_cases(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="CSRF origins required"):
        _test_app(
            tmp_path,
            cors_origins=["https://app.test"],
            csrf_origins=[],
            cookie_auth_enabled=True,
        )

    with pytest.raises(RuntimeError, match="subset of CORS origins"):
        _test_app(
            tmp_path,
            cors_origins=[],
            csrf_origins=["https://app.test"],
            cookie_auth_enabled=True,
        )

    app = _test_app(
        tmp_path,
        cors_origins=["https://app.test"],
        csrf_origins=["https://csrf.test"],
        cookie_auth_enabled=False,
    )
    assert app.state.csrf_origins == ["https://csrf.test"]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "",
        "app.test",
        "https://user:pass@app.test",
        "https://app.test/path",
        "https://app.test?query=1",
        "https://app.test#fragment",
        "https://app.test:not-a-port",
    ],
)
def test_settings_reject_ambiguous_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", cors_origins=[origin])  # type: ignore[call-arg]


def test_session_cookie_uses_configured_ttl_and_security_attributes() -> None:
    request = type(
        "Request",
        (),
        {
            "app": type(
                "App",
                (),
                {
                    "state": type(
                        "State",
                        (),
                        {"cookie_secure": True, "session_ttl_seconds": 1234},
                    )()
                },
            )()
        },
    )()
    response = Response()

    _set_session_cookie(request, response, "secret")  # type: ignore[arg-type]
    cookie = response.headers["set-cookie"].lower()
    assert "sf_session=secret" in cookie
    assert "max-age=1234" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie

    delete_response = Response()
    _delete_session_cookie(request, delete_response)  # type: ignore[arg-type]
    expired = delete_response.headers["set-cookie"].lower()
    assert "max-age=0" in expired
    assert "httponly" in expired
    assert "secure" in expired


def test_iam_v1_array_and_v2_page_are_distinct_openapi_contracts(tmp_path: Path) -> None:
    schema = _test_app(tmp_path).openapi()
    v1 = schema["paths"]["/api/v1/iam/users"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    v2 = schema["paths"]["/api/v2/iam/users"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert "list_UserSummaryResponse" in v1["$ref"]
    assert "Page_UserSummaryResponse" in v2["$ref"]


def test_openapi_has_stable_ids_cookie_security_and_csrf_headers(tmp_path: Path) -> None:
    schema = _test_app(tmp_path).openapi()
    operations = [
        operation
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    operation_ids = [operation["operationId"] for operation in operations]
    assert len(operation_ids) == len(set(operation_ids)) == 15
    assert "APIKeyCookie" in schema["components"]["securitySchemes"]

    login = schema["paths"]["/api/v1/auth/login"]["post"]
    logout = schema["paths"]["/api/v1/auth/logout"]["post"]
    upload = schema["paths"]["/api/v1/files"]["post"]
    delete = schema["paths"]["/api/v1/files/{file_id}"]["delete"]
    for operation in (login, logout, upload, delete):
        origin = next(
            parameter for parameter in operation["parameters"] if parameter["name"] == "Origin"
        )
        assert origin["required"] is True
    for operation in (logout, upload, delete):
        csrf = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "X-CSRF-Token"
        )
        assert csrf["required"] is True

    download = schema["paths"]["/api/v1/files/{file_id}"]["get"]
    parameter_names = {parameter["name"] for parameter in download["parameters"]}
    assert {"Range", "If-Range", "If-None-Match"} <= parameter_names
    assert "ETag" in download["responses"]["200"]["headers"]
    assert "Content-Range" in download["responses"]["206"]["headers"]
    assert "WWW-Authenticate" in login["responses"]["401"]["headers"]
    assert "Retry-After" in login["responses"]["429"]["headers"]


def test_openapi_snapshot_matches_checked_in_contract(tmp_path: Path) -> None:
    snapshot_path = Path("docs/openapi.json")
    assert snapshot_path.exists()
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert _test_app(tmp_path).openapi() == expected


@pytest.mark.parametrize(
    "values",
    [{"page": 0}, {"page_size": 0}, {"page_size": 201}],
)
def test_page_bounds_reject_invalid_values(values: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        PageParams(**values)
