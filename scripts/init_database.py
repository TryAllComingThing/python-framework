"""Install database schema and idempotent framework-owned seed data.

Usage:
    DATABASE_URL=postgresql+asyncpg://... python -m scripts.init_database
    DATABASE_URL=... FRAMEWORK_ADMIN_PASSWORD=... python -m scripts.init_database --admin-user admin

No default administrator password is ever generated or stored in the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.modules.auth.security import hash_password, normalize_username
from app.modules.iam.models import Menu, Permission, Role, User, role_permissions, user_roles

# Permissions implemented and enforced by the current HTTP application.
SEED_VERSION = "2026.11.20.2"
BUILTIN_PERMISSIONS: tuple[str, ...] = (
    "system:user:list",
    "file:upload",
    "file:read:all",
    "file:delete:all",
)
ADMIN_ROLE = "framework_admin"
ADMIN_SCOPE = "ALL"
BUILTIN_MENU = ("用户管理", "/iam/users", "system:user:list")


async def seed_framework(
    db: AsyncSession, admin_user: str | None = None, admin_password: str | None = None
) -> None:
    """Insert missing framework-owned records, without overwriting local customizations."""
    if admin_user and (not admin_password or len(admin_password) < 12):
        raise ValueError("Admin password must be explicitly provided and >= 12 characters")
    if admin_password and not admin_user:
        raise ValueError("Admin username required when password is provided")

    for code in BUILTIN_PERMISSIONS:
        await db.execute(
            insert(Permission)
            .values(code=code)
            .on_conflict_do_nothing(index_elements=[Permission.code])
        )
    await db.execute(
        insert(Role)
        .values(name=ADMIN_ROLE, scope=ADMIN_SCOPE, active=True)
        .on_conflict_do_nothing(index_elements=[Role.name])
    )
    role_id = (await db.execute(select(Role.id).where(Role.name == ADMIN_ROLE))).scalar_one()
    for code in BUILTIN_PERMISSIONS:
        permission_id = (
            await db.execute(select(Permission.id).where(Permission.code == code))
        ).scalar_one()
        await db.execute(
            insert(role_permissions)
            .values(role_id=role_id, permission_id=permission_id)
            .on_conflict_do_nothing()
        )
    name, path, permission_code = BUILTIN_MENU
    # Database unique constraint protects all writers, not just this installer.
    await db.execute(
        insert(Menu)
        .values(name=name, path=path, permission_code=permission_code, order_num=10, active=True)
        .on_conflict_do_nothing(index_elements=[Menu.path])
    )

    if admin_user:
        normalized_user = normalize_username(admin_user)
        user_id = (
            await db.execute(
                select(User.id).where(
                    func.lower(User.username) == func.lower(literal(normalized_user))
                )
            )
        ).scalar_one_or_none()
        if user_id is None:
            if admin_password is None:
                raise ValueError("Admin password is required for a new administrator")
            # Existing accounts are never silently reset or promoted by the installer.
            account = User(
                username=normalized_user,
                password_hash=hash_password(admin_password),
                active=True,
                auth_version=1,
            )
            db.add(account)
            await db.flush()
            user_id = account.id
            await db.execute(
                insert(user_roles).values(user_id=user_id, role_id=role_id).on_conflict_do_nothing()
            )
        else:
            raise ValueError("Admin username already exists; use normal IAM workflows")


async def install_seed(url: str, admin_user: str | None, password: str | None) -> None:
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                # Avoid duplicate menu creation across concurrent installers.
                from sqlalchemy import text

                await session.execute(text("SELECT pg_advisory_xact_lock(61203333)"))
                await seed_framework(session, admin_user, password)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate and seed the framework database")
    parser.add_argument("--admin-user", help="Explicit first administrator username")
    parser.add_argument("--seed-only", action="store_true", help="Skip Alembic upgrade")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url or not settings.database_url.startswith("postgresql+asyncpg://"):
        parser.error("DATABASE_URL must be a PostgreSQL asyncpg URL")
    password = os.environ.get("FRAMEWORK_ADMIN_PASSWORD")
    if args.admin_user and not password:
        parser.error("FRAMEWORK_ADMIN_PASSWORD must be set when --admin-user is used")
    if not args.seed_only:
        project_root = Path(__file__).resolve().parents[1]
        # Build the Alembic config in code so an installed wheel does not need
        # the source-tree-only alembic.ini file.
        config = Config()
        config.set_main_option("script_location", str(project_root / "migrations"))
        config.set_main_option("prepend_sys_path", str(project_root))
        command.upgrade(config, "head")
    asyncio.run(install_seed(settings.database_url, args.admin_user, password))
    print(f"Database schema and built-in records initialized (seed {SEED_VERSION})")


if __name__ == "__main__":
    main()
