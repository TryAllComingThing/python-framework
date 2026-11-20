"""Authorized file metadata projections and pagination queries."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import Page, PageParams
from app.modules.files.models import FileRecord
from app.modules.files.schemas import FileMetadataResponse


def to_file_metadata(record: FileRecord) -> FileMetadataResponse:
    """Expose public fields without leaking the private object key."""
    return FileMetadataResponse(
        id=record.id,
        name=record.original_name,
        size=record.size,
        sha256=record.sha256,
        content_type=record.content_type,
    )


async def page_file_metadata(
    db: AsyncSession,
    *,
    actor_id: int,
    permissions: frozenset[str],
    page: PageParams,
) -> Page[FileMetadataResponse]:
    """Apply ownership policy before counting or retrieving metadata."""
    query = select(FileRecord)
    if "file:read:all" not in permissions:
        query = query.where(FileRecord.owner_id == actor_id)
    total = (
        await db.execute(select(func.count()).select_from(query.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                query.order_by(FileRecord.id)
                .offset((page.page - 1) * page.page_size)
                .limit(page.page_size)
            )
        )
        .scalars()
        .all()
    )
    return Page[FileMetadataResponse](
        items=[to_file_metadata(row) for row in rows],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
