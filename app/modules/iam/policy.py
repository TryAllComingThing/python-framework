"""Single-tenant IAM policy; tenant isolation is NOT implemented.

Do not use this framework for multi-tenant workloads without tenant-aware
models, queries, audit boundaries, and cross-tenant security tests.
"""

from dataclasses import dataclass

from sqlalchemy import Select, false, or_

from app.core.codes import ErrorCode
from app.core.errors import AppError
from app.modules.iam.models import User


@dataclass(frozen=True)
class Principal:
    """Effective authenticated principal after active-role filtering."""

    user_id: int
    department_id: int | None
    permissions: frozenset[str]
    scopes: frozenset[str]
    department_ids: frozenset[int] = frozenset()
    custom_department_ids: frozenset[int] = frozenset()


def require_permission(principal: Principal, permission: str) -> None:
    """Reject access unless the principal holds the required permission."""
    if permission not in principal.permissions:
        raise AppError(ErrorCode.FORBIDDEN, 403)


def apply_user_scope(
    stmt: Select[tuple[User]],
    principal: Principal,
    model: type[User],
) -> Select[tuple[User]]:
    """Restrict user queries to the union of granted scopes; default deny."""
    if "ALL" in principal.scopes:
        return stmt
    filters = [model.id == principal.user_id] if "SELF" in principal.scopes else []
    if "DEPARTMENT" in principal.scopes and principal.department_id is not None:
        filters.append(model.department_id == principal.department_id)
    if "DEPARTMENT_AND_CHILDREN" in principal.scopes and principal.department_ids:
        filters.append(model.department_id.in_(principal.department_ids))
    if "CUSTOM" in principal.scopes and principal.custom_department_ids:
        filters.append(model.department_id.in_(principal.custom_department_ids))
    return stmt.where(or_(*filters) if filters else false())
