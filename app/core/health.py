"""Liveness and PostgreSQL readiness probes."""

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.common.openapi import error_responses
from app.core.codes import ErrorCode
from app.core.errors import AppError

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", operation_id="health_live")
async def live() -> dict[str, str]:
    """Report process liveness without touching dependencies."""
    return {"status": "alive"}


@router.get(
    "/ready",
    operation_id="health_ready",
    responses=error_responses(503),
)
async def ready(request: Request) -> dict[str, str]:
    """Report readiness only when PostgreSQL accepts a trivial query."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise AppError(ErrorCode.DATABASE_UNAVAILABLE, 503)
    try:
        async with db.sessions() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise AppError(ErrorCode.DATABASE_UNAVAILABLE, 503) from exc
    return {"status": "ready"}
