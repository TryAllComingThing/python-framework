from __future__ import annotations

import asyncio
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import LoginAttempt, LoginSession
from app.modules.auth.rate_limit import account_bucket, register_failure
from app.modules.auth.security import hash_password
from app.modules.auth.service import invalidate_user_authorization
from app.modules.files.models import FileCleanupJob
from app.modules.files.service import retry_file_cleanup
from app.modules.iam.models import User

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _session_factory(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _delete_user_artifacts(factory: async_sessionmaker[AsyncSession], user_id: int) -> None:
    async with factory() as db:
        await db.execute(delete(AuditEvent).where(AuditEvent.actor_id == user_id))
        await db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def _insert_user_with_sessions(factory: async_sessionmaker[AsyncSession]) -> int:
    suffix = secrets.token_hex(6)
    async with factory() as db:
        user = User(
            username=f"integration-{suffix}",
            password_hash="unused-in-integration-test",
            active=True,
            auth_version=1,
        )
        db.add(user)
        await db.flush()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.add_all(
            [
                LoginSession(
                    user_id=user.id,
                    token_digest=secrets.token_hex(32),
                    csrf_digest=secrets.token_hex(32),
                    auth_version=1,
                    expires_at=expires_at,
                ),
                LoginSession(
                    user_id=user.id,
                    token_digest=secrets.token_hex(32),
                    csrf_digest=secrets.token_hex(32),
                    auth_version=1,
                    expires_at=expires_at,
                ),
            ]
        )
        await db.commit()
        return user.id


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
async def test_postgres_alembic_tables_are_queryable() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            version: str = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert version == "1_quality_remediation"
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
async def test_postgres_constraints_and_case_insensitive_username_uniqueness() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            index_definition: str = (
                await connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = current_schema() "
                        "AND indexname = 'ix_sf_users_username_lower'"
                    )
                )
            ).scalar_one()
            constraints: set[str] = set(
                (
                    await connection.execute(
                        text("SELECT conname FROM pg_constraint WHERE conname = ANY(:names)"),
                        {
                            "names": [
                                "ck_sf_file_records_size_positive",
                                "ck_sf_file_records_sha256",
                                "ck_sf_file_cleanup_jobs_attempts",
                                "ck_sf_login_attempts_failures",
                            ]
                        },
                    )
                )
                .scalars()
                .all()
            )

        assert "UNIQUE INDEX" in index_definition
        assert "lower(" in index_definition and "username" in index_definition
        assert constraints == {
            "ck_sf_file_records_size_positive",
            "ck_sf_file_records_sha256",
            "ck_sf_file_cleanup_jobs_attempts",
            "ck_sf_login_attempts_failures",
        }

        suffix = secrets.token_hex(6)
        password_hash = hash_password("not-used-in-this-test")
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text(
                        "INSERT INTO sf_users (username, password_hash) "
                        "VALUES (:username, :password_hash)"
                    ),
                    {"username": f"CaseProbe{suffix}", "password_hash": password_hash},
                )
                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "INSERT INTO sf_users (username, password_hash) "
                                "VALUES (:username, :password_hash)"
                            ),
                            {"username": f"caseprobe{suffix}", "password_hash": password_hash},
                        )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
async def test_authorization_invalidation_commits_state_and_audit_together() -> None:
    engine, factory = _session_factory(_database_url())
    user_id: int | None = None
    try:
        user_id = await _insert_user_with_sessions(factory)
        async with factory() as db:
            await invalidate_user_authorization(
                db,
                user_id=user_id,
                actor_id=user_id,
                request_id="integration-authz-commit",
            )

        async with factory() as db:
            auth_version = (
                await db.execute(select(User.auth_version).where(User.id == user_id))
            ).scalar_one()
            sessions = (
                (await db.execute(select(LoginSession).where(LoginSession.user_id == user_id)))
                .scalars()
                .all()
            )
            audit_count = (
                await db.execute(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.actor_id == user_id,
                        AuditEvent.action == "auth.authorization_changed",
                    )
                )
            ).scalar_one()

        assert auth_version == 2
        assert sessions and all(session.revoked_at is not None for session in sessions)
        assert audit_count == 1
    finally:
        if user_id is not None:
            await _delete_user_artifacts(factory, user_id)
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
async def test_authorization_invalidation_rolls_back_state_when_audit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory = _session_factory(_database_url())
    user_id: int | None = None

    async def fail_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr("app.modules.auth.service.record_audit", fail_audit)
    try:
        user_id = await _insert_user_with_sessions(factory)
        async with factory() as db:
            with pytest.raises(RuntimeError, match="simulated audit failure"):
                await invalidate_user_authorization(
                    db,
                    user_id=user_id,
                    actor_id=user_id,
                    request_id="integration-authz-rollback",
                )

        async with factory() as db:
            auth_version = (
                await db.execute(select(User.auth_version).where(User.id == user_id))
            ).scalar_one()
            active_sessions = (
                await db.execute(
                    select(func.count())
                    .select_from(LoginSession)
                    .where(
                        LoginSession.user_id == user_id,
                        LoginSession.revoked_at.is_(None),
                    )
                )
            ).scalar_one()
            audit_count = (
                await db.execute(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.actor_id == user_id)
                )
            ).scalar_one()

        assert auth_version == 1
        assert active_sessions == 2
        assert audit_count == 0
    finally:
        if user_id is not None:
            await _delete_user_artifacts(factory, user_id)
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
async def test_login_failure_counter_is_atomic_under_concurrent_writers() -> None:
    engine, factory = _session_factory(_database_url())
    bucket = account_bucket(f"concurrent-{secrets.token_hex(8)}")

    async def fail_once() -> None:
        async with factory() as db:
            await register_failure(db, bucket, threshold=5)
            await db.commit()

    try:
        await asyncio.gather(*(fail_once() for _ in range(5)))
        async with factory() as db:
            attempt = (
                await db.execute(select(LoginAttempt).where(LoginAttempt.bucket == bucket))
            ).scalar_one()

        assert attempt.failures == 5
        assert attempt.locked_until is not None
    finally:
        async with factory() as db:
            await db.execute(delete(LoginAttempt).where(LoginAttempt.bucket == bucket))
            await db.commit()
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
async def test_cleanup_lease_allows_only_one_concurrent_claim() -> None:
    engine, factory = _session_factory(_database_url())
    object_key = secrets.token_hex(20) + ".txt"

    class RecordingStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete(self, key: str) -> None:
            self.deleted.append(key)

    storage = RecordingStorage()
    try:
        async with factory() as db:
            db.add(FileCleanupJob(object_key=object_key, reason="integration_lease"))
            await db.commit()

        async def clean_once() -> tuple[int, int]:
            async with factory() as db:
                return await retry_file_cleanup(db, storage, limit=1)  # type: ignore[arg-type]

        outcomes = await asyncio.gather(clean_once(), clean_once())

        assert sum(completed for completed, _ in outcomes) == 1
        assert storage.deleted == [object_key]
        async with factory() as db:
            remaining = (
                await db.execute(
                    select(func.count())
                    .select_from(FileCleanupJob)
                    .where(FileCleanupJob.object_key == object_key)
                )
            ).scalar_one()
        assert remaining == 0
    finally:
        async with factory() as db:
            await db.execute(delete(FileCleanupJob).where(FileCleanupJob.object_key == object_key))
            await db.commit()
        await engine.dispose()


def _maintenance_url(database_url: str) -> str:
    return make_url(database_url).set(database="postgres").render_as_string(hide_password=False)


async def _create_temporary_database(admin_url: str, database: str) -> None:
    if not re.fullmatch(r"pf_migration_[0-9a-f]{16}", database):
        raise ValueError("unsafe temporary database name")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
    except DBAPIError as exc:
        if "permission denied to create database" in str(exc).lower():
            pytest.skip("TEST_DATABASE_URL role cannot create a temporary database")
        raise
    finally:
        await engine.dispose()


async def _drop_temporary_database(admin_url: str, database: str) -> None:
    if not re.fullmatch(r"pf_migration_[0-9a-f]{16}", database):
        raise ValueError("unsafe temporary database name")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    finally:
        await engine.dispose()


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


async def _read_alembic_version(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            exists: str | None = (
                await connection.execute(text("SELECT to_regclass('public.alembic_version')"))
            ).scalar_one()
            if exists is None:
                return None
            return (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
def test_postgres_empty_install_upgrade_downgrade_and_reupgrade() -> None:
    admin_url = _maintenance_url(_database_url())
    database = f"pf_migration_{secrets.token_hex(8)}"
    asyncio.run(_create_temporary_database(admin_url, database))
    temporary_url = (
        make_url(_database_url()).set(database=database).render_as_string(hide_password=False)
    )
    try:
        baseline = _run_alembic(temporary_url, "upgrade", "0_baseline")
        assert baseline.returncode == 0, baseline.stderr
        assert asyncio.run(_read_alembic_version(temporary_url)) == "0_baseline"

        upgraded = _run_alembic(temporary_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        assert asyncio.run(_read_alembic_version(temporary_url)) == "1_quality_remediation"

        downgraded = _run_alembic(temporary_url, "downgrade", "0_baseline")
        assert downgraded.returncode == 0, downgraded.stderr
        assert asyncio.run(_read_alembic_version(temporary_url)) == "0_baseline"

        reupgraded = _run_alembic(temporary_url, "upgrade", "head")
        assert reupgraded.returncode == 0, reupgraded.stderr
        assert asyncio.run(_read_alembic_version(temporary_url)) == "1_quality_remediation"

        removed = _run_alembic(temporary_url, "downgrade", "base")
        assert removed.returncode == 0, removed.stderr
        assert asyncio.run(_read_alembic_version(temporary_url)) is None

        clean_install = _run_alembic(temporary_url, "upgrade", "head")
        assert clean_install.returncode == 0, clean_install.stderr
        assert asyncio.run(_read_alembic_version(temporary_url)) == "1_quality_remediation"
    finally:
        asyncio.run(_drop_temporary_database(admin_url, database))
