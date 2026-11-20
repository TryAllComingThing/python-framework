"""Load authoritative department hierarchy and role-specific custom grants."""

from collections.abc import Sequence
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.models import Department, RoleDepartment


async def descendants(db: AsyncSession, department_id: int | None) -> frozenset[int]:
    """Return the department and descendants using a terminating recursive CTE.

    ``UNION`` (not ``UNION ALL``) prevents cycles from producing unbounded rows.
    The explicit 10,001-row cap fails closed for pathological hierarchies.
    """
    if department_id is None:
        return frozenset()
    tree = (
        select(Department.id.label("id"))
        .where(Department.id == department_id)
        .cte("department_tree", recursive=True)
    )
    tree = tree.union(select(Department.id).join(tree, Department.parent_id == tree.c.id))
    ids = cast(
        list[int],
        (await db.execute(select(tree.c.id).limit(10_001))).scalars().all(),
    )
    if len(ids) > 10_000:
        raise ValueError("department hierarchy exceeds limit")
    return frozenset(ids)


async def custom_grants(
    db: AsyncSession,
    role_ids: Sequence[int],
) -> frozenset[int]:
    """Return the union of explicitly granted departments for custom roles."""
    if not role_ids:
        return frozenset()
    ids = cast(
        list[int],
        (
            await db.execute(
                select(RoleDepartment.department_id).where(RoleDepartment.role_id.in_(role_ids))
            )
        )
        .scalars()
        .all(),
    )
    return frozenset(ids)
