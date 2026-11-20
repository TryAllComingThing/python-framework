"""Reusable OpenAPI error response declarations."""

from __future__ import annotations

from typing import Any

from app.common.responses import ApiErrorResponse

_ERROR_DESCRIPTIONS = {
    400: "Bad request",
    401: "Authentication required",
    403: "Forbidden or CSRF validation failed",
    404: "Resource absent or not authorized",
    405: "Method not allowed",
    406: "Not acceptable",
    409: "Conflict",
    412: "Precondition failed",
    413: "Payload too large",
    415: "Unsupported media type",
    416: "Range not satisfiable",
    422: "Validation error",
    428: "Precondition required",
    429: "Rate limit exceeded",
    500: "Internal server error",
    503: "Required infrastructure unavailable",
}

ORIGIN_HEADER: dict[str, Any] = {
    "name": "Origin",
    "in": "header",
    "required": True,
    "description": "Trusted browser origin used for CSRF origin validation.",
    "schema": {"type": "string"},
}

CSRF_HEADER: dict[str, Any] = {
    "name": "X-CSRF-Token",
    "in": "header",
    "required": True,
    "description": "Session-bound CSRF token returned by the login endpoint.",
    "schema": {"type": "string"},
}

RANGE_HEADER: dict[str, Any] = {
    "name": "Range",
    "in": "header",
    "required": False,
    "description": "Single RFC 9110 byte range such as bytes=0-1023.",
    "schema": {"type": "string"},
}

IF_RANGE_HEADER: dict[str, Any] = {
    "name": "If-Range",
    "in": "header",
    "required": False,
    "description": "Only honor Range when the supplied strong ETag still matches.",
    "schema": {"type": "string"},
}

IF_NONE_MATCH_HEADER: dict[str, Any] = {
    "name": "If-None-Match",
    "in": "header",
    "required": False,
    "description": "Return 304 when the supplied entity tag matches the file digest.",
    "schema": {"type": "string"},
}


def _header(description: str, schema_type: str = "string") -> dict[str, Any]:
    return {"description": description, "schema": {"type": schema_type}}


SET_COOKIE_HEADER = _header("Server-side session cookie; HttpOnly and same-site.")
CACHE_CONTROL_HEADER = _header("Caching policy for authenticated responses.")
ETAG_HEADER = _header("Strong entity tag derived from the stored SHA-256 digest.")
CONTENT_DISPOSITION_HEADER = _header("Attachment filename encoded using RFC 5987.")
CONTENT_RANGE_HEADER = _header("Inclusive byte range and total object size.")
ACCEPT_RANGES_HEADER = _header("Advertises byte-range support.")

AUTH_COOKIE_RESPONSE_HEADERS: dict[str, Any] = {
    "Set-Cookie": SET_COOKIE_HEADER,
    "Cache-Control": CACHE_CONTROL_HEADER,
}

DOWNLOAD_RESPONSE_HEADERS: dict[str, Any] = {
    "Cache-Control": CACHE_CONTROL_HEADER,
    "ETag": ETAG_HEADER,
    "Content-Disposition": CONTENT_DISPOSITION_HEADER,
    "Accept-Ranges": ACCEPT_RANGES_HEADER,
}

RANGE_RESPONSE_HEADERS: dict[str, Any] = {
    **DOWNLOAD_RESPONSE_HEADERS,
    "Content-Range": CONTENT_RANGE_HEADER,
}


def _error_headers(status: int) -> dict[str, Any] | None:
    if status == 401:
        return {
            "WWW-Authenticate": _header(
                "Authentication challenge using the application session scheme."
            )
        }
    if status == 429:
        return {"Retry-After": _header("Seconds before retrying the request.", "integer")}
    return None


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Build independent OpenAPI response declarations for selected statuses."""
    responses: dict[int | str, dict[str, Any]] = {}
    for status in statuses:
        response: dict[str, Any] = {
            "model": ApiErrorResponse,
            "description": _ERROR_DESCRIPTIONS[status],
        }
        if headers := _error_headers(status):
            response["headers"] = headers
        responses[status] = response
    return responses
