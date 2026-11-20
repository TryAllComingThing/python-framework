"""Alembic environment for the PostgreSQL async application metadata."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.modules.audit.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.files.models  # noqa: F401
import app.modules.iam.models  # noqa: F401
from app.core.config import get_settings
from app.models.base import Base
from migrations.preflight import assert_username_keys_unique

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = get_settings().database_url
if not url:
    raise RuntimeError("DATABASE_URL required for Alembic")
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without opening a database connection."""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations against an established synchronous facade connection."""
    assert_username_keys_unique(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async engine and run migrations through its sync facade."""
    configuration: dict[str, Any] = config.get_section(
        config.config_ini_section,
        {},
    )
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # SQLAlchemy 2 begins an implicit transaction around the connection.
        # Alembic's migration transaction can finish successfully while this
        # outer transaction is still open; closing without an explicit commit
        # rolls back every DDL statement. Keep this commit outside the sync
        # facade so a failed migration still rolls back via context cleanup.
        await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
