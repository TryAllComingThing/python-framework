import hashlib
import hmac
import secrets
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Request

from app.core.codes import ErrorCode
from app.core.errors import AppError

hasher = PasswordHasher()
SESSION_COOKIE_NAME = "sf_session"


def normalize_username(value: str) -> str:
    """Normalize account lookup input and reject unsafe control characters."""
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized or len(normalized) > 100:
        raise ValueError("invalid username")
    if any(unicodedata.category(char) in ("Cc", "Cf", "Cs") for char in normalized):
        raise ValueError("invalid username")
    return normalized


def username_key(value: str) -> str:
    """Return the canonical case-insensitive key used by lookup and throttling.

    PostgreSQL uniqueness and lookup use ``lower(username)``; this helper is the
    Python-side key for throttling and non-SQL consumers. Keeping it on
    ``lower()`` avoids ``casefold()`` introducing different keys (for example,
    ``ß`` -> ``ss``) that the database constraint does not use. Login lookup
    itself applies PostgreSQL ``lower()`` to both the column and the input.
    """
    return normalize_username(value).lower()


def hash_password(password: str) -> str:
    """Derive a password hash using the configured password hasher."""
    return hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    """Verify a supplied password against a stored hash."""
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, ValueError):
        return False


def new_secret() -> str:
    """Generate a cryptographically random session secret."""
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    """Hash a secret before storing or comparing it."""
    return hashlib.sha256(value.encode()).hexdigest()


def constant_equal(left: str, right: str) -> bool:
    """Compare two digests using constant-time equality."""
    return hmac.compare_digest(left, right)


def check_csrf(
    request: Request,
    expected_digest: str,
    allowed_origins: list[str],
) -> None:
    """Enforce CSRF origin and token requirements for cookie-authenticated writes."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin or origin not in allowed_origins:
        raise AppError(ErrorCode.FORBIDDEN, 403)
    token = request.headers.get("X-CSRF-Token", "")
    if not token or not constant_equal(digest(token), expected_digest):
        raise AppError(ErrorCode.FORBIDDEN, 403)


# Stable precomputed Argon2 hash. Never compute a fresh hash for each login attempt.
_DUMMY_PASSWORD_HASH = hasher.hash("not-a-real-user-password")


def verify_login_password(password_hash: str | None, password: str) -> bool:
    """Run Argon2 verification for both existing and unknown accounts."""
    return verify_password(password_hash or _DUMMY_PASSWORD_HASH, password)
