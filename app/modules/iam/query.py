"""IAM user queries; always apply the principal's data scope before pagination."""

from collections.abc import Sequence
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import Page, PageParams
from app.modules.iam.models import User
from app.modules.iam.policy import Principal, apply_user_scope
from app.modules.iam.schemas import UserSummaryResponse


def _summarize(user: User) -> UserSummaryResponse:
    return UserSummaryResponse(id=user.id, username=user.username)


async def list_user_summaries(
    db: AsyncSession,
    principal: Principal,
    *,
    limit: int = 100,
) -> list[UserSummaryResponse]:
    """Return the historical, capped V1 representation."""
    scoped = apply_user_scope(select(User), principal, User)
    rows = cast(
        Sequence[User],
        (await db.execute(scoped.order_by(User.id).limit(limit))).scalars().all(),
    )
    return [_summarize(user) for user in rows]


async def page_user_summaries(
    db: AsyncSession,
    principal: Principal,
    page: PageParams,
) -> Page[UserSummaryResponse]:
    """Count and page only authorized rows; deterministic ID ordering."""
    scoped = apply_user_scope(select(User), principal, User)
    total = (
        await db.execute(select(func.count()).select_from(scoped.order_by(None).subquery()))
    ).scalar_one()
    rows = cast(
        Sequence[User],
        (
            await db.execute(
                scoped.order_by(User.id)
                .offset((page.page - 1) * page.page_size)
                .limit(page.page_size)
            )
        )
        .scalars()
        .all(),
    )
    return Page[UserSummaryResponse](
        items=[_summarize(user) for user in rows],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
