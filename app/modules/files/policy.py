"""Owner access or explicit IAM global permission. No trust in client owner_id."""

from app.core.codes import ErrorCode
from app.core.errors import AppError


def require_upload(permissions: frozenset[str]) -> None:
    """Reject upload unless the principal has the explicit upload grant."""
    if "file:upload" not in permissions:
        raise AppError(ErrorCode.FORBIDDEN, 403)


def require_file_action(
    *, owner_id: int, actor_id: int, permissions: frozenset[str], action: str
) -> None:
    """Authorize owner or all-files grant; conceal inaccessible file existence."""
    if action not in ("read", "delete"):
        raise ValueError("unsupported file action")
    if owner_id != actor_id and f"file:{action}:all" not in permissions:
        # Do not disclose existence to an unauthorized user.
        raise AppError(ErrorCode.NOT_FOUND, 404)
