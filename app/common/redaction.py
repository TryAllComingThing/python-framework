"""Defensive structured-field redaction. Avoid logging free-form secrets."""

import re
from typing import Any

SENSITIVE = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "set_cookie",
        "secret",
        "api_key",
        "apikey",
        "csrf_token",
        "csrf",
        "session_token",
        "bearer_token",
        "authorization_header",
        "password_hash",
        "secret_key",
        "x_api_key",
        "x_csrf_token",
        "private_key",
        "client_secret",
        "credential",
    }
)


def _sensitive(name: object) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized.casefold()).strip("_")
    return normalized in SENSITIVE or any(normalized.endswith("_" + x) for x in SENSITIVE)


def redact(value: Any) -> Any:
    """Recursively mask known credential fields in structured log payloads."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _sensitive(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
