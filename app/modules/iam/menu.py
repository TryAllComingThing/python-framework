"""Menu tree is an authorization-filtered projection, not the security boundary."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.models import Menu
from app.modules.iam.schemas import MenuResponse


async def visible_menus(
    db: AsyncSession,
    permissions: frozenset[str],
) -> list[MenuResponse]:
    """Return active menus whose optional permission is granted."""
    rows = (
        (
            await db.execute(
                select(Menu).where(Menu.active.is_(True)).order_by(Menu.order_num, Menu.id)
            )
        )
        .scalars()
        .all()
    )
    allowed = [
        menu for menu in rows if not menu.permission_code or menu.permission_code in permissions
    ]
    ids = {menu.id for menu in allowed}
    return [
        MenuResponse(
            id=menu.id,
            parent_id=menu.parent_id if menu.parent_id in ids else None,
            name=menu.name,
            path=menu.path,
            permission=menu.permission_code,
        )
        for menu in allowed
    ]
