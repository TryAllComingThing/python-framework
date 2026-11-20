from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.common.i18n import negotiate_locale, translate
from app.common.redaction import redact
from app.core.codes import ErrorCode
from app.core.errors import AppError, error_response


def test_error_status_mapping_is_consistent() -> None:
    with pytest.raises(ValueError):
        AppError(ErrorCode.BAD_REQUEST, 500)
    with pytest.raises(ValueError):
        AppError(ErrorCode.SERVICE_UNAVAILABLE, 500)


def test_error_response_uses_locale_and_request_id() -> None:
    request = SimpleNamespace(state=SimpleNamespace(locale="en-US", request_id="req-1"))
    response = error_response(request, str(ErrorCode.SERVICE_UNAVAILABLE), 503)  # type: ignore[arg-type]
    assert response.status_code == 503
    assert response.headers["content-language"] == "en-US"


def test_error_response_adds_protocol_headers_and_allows_explicit_override() -> None:
    request = SimpleNamespace(state=SimpleNamespace(locale="zh-CN", request_id="req-1"))
    unauthorized = error_response(request, str(ErrorCode.UNAUTHORIZED), 401)  # type: ignore[arg-type]
    assert unauthorized.headers["www-authenticate"] == 'Session realm="python-framework"'

    limited = error_response(
        request,  # type: ignore[arg-type]
        str(ErrorCode.TOO_MANY_REQUESTS),
        429,
        headers={"Retry-After": "900"},
    )
    assert limited.headers["retry-after"] == "900"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("en-US,en;q=0.9", "en-US"),
        ("zh-CN;q=0.4,en-US;q=0.8", "en-US"),
        ("fr-FR", "zh-CN"),
    ],
)
def test_locale_negotiation(header: str, expected: str) -> None:
    assert negotiate_locale(header) == expected


def test_all_error_codes_have_bilingual_messages() -> None:
    for code in ErrorCode:
        assert translate(str(code), "zh-CN") != str(code)
        assert translate(str(code), "en-US") != str(code)


def test_redaction_covers_secret_aliases_in_nested_structures() -> None:
    payload = {
        "password_hash": "hash",
        "secret_key": "secret",
        "authorization_header": "Bearer token",
        "nested": [{"x-csrf-token": "csrf", "safe": "visible"}],
    }

    assert redact(payload) == {
        "password_hash": "[REDACTED]",
        "secret_key": "[REDACTED]",
        "authorization_header": "[REDACTED]",
        "nested": [{"x-csrf-token": "[REDACTED]", "safe": "visible"}],
    }
