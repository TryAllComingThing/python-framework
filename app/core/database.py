from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.codes import ErrorCode
from app.core.errors import AppError


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def close(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database | None = getattr(request.app.state, "db", None)
    if db is None:
        raise AppError(ErrorCode.DATABASE_UNAVAILABLE, 503)
    async with db.sessions() as session:
        yield session


async def initialize_database(app: FastAPI, url: str | None) -> None:
    app.state.db = Database(url) if url else None


async def close_database(app: FastAPI) -> None:
    db = getattr(app.state, "db", None)
    if db:
        await db.close()
    app.state.db = None
