"""File lifecycle: authorize -> metadata -> private storage -> durable cleanup."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.common.files import validate_upload
from app.core.codes import ErrorCode
from app.core.errors import AppError
from app.infrastructure.malware import (
    MalwareDetectedError,
    MalwareScannerUnavailableError,
    scan_with_clamd,
)
from app.infrastructure.storage import StoragePort
from app.infrastructure.upload_failures import record_failed_cleanup, record_uncertain_delete
from app.modules.audit.service import record_audit
from app.modules.files.models import FileCleanupJob, FileRecord
from app.modules.files.policy import require_file_action, require_upload

log = logging.getLogger("python_framework.files")
CLEANUP_LEASE_SECONDS = 300


async def upload_file(
    db: AsyncSession,
    storage: StoragePort,
    *,
    actor_id: int,
    permissions: frozenset[str],
    filename: str,
    data: bytes,
    request_id: str,
    max_bytes: int = 5_000_000,
    scan_enabled: bool = False,
    clamd_socket: str = "/run/clamav/clamd.ctl",
) -> FileRecord:
    """Validate, scan and persist an upload, with durable cleanup intents.

    Side effects: writes one private object and one DB metadata/audit transaction.
    Failure modes: validation/scan failures write no object; storage errors may
    leave no committed DB row; a failed cleanup after DB rollback is represented
    by a FileCleanupJob in a fresh transaction or a fallback journal.
    """
    require_upload(permissions)
    if len(data) > max_bytes:
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, 413)
    try:
        validated = await run_in_threadpool(validate_upload, data, filename, max_bytes=max_bytes)
    except ValueError:
        raise AppError(ErrorCode.BAD_REQUEST, 400) from None
    if scan_enabled:
        try:
            await run_in_threadpool(scan_with_clamd, data, clamd_socket)
        except MalwareDetectedError:
            raise AppError(ErrorCode.BAD_REQUEST, 400) from None
        except MalwareScannerUnavailableError:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, 503) from None
    try:
        stored = await run_in_threadpool(storage.put, data, validated.suffix)
    except OSError:
        raise AppError(ErrorCode.INTERNAL_ERROR, 500) from None
    record = FileRecord(
        owner_id=actor_id,
        object_key=stored.key,
        original_name=validated.filename,
        content_type=validated.content_type,
        size=stored.size,
        sha256=stored.sha256,
    )
    try:
        db.add(record)
        await db.flush()
        await record_audit(
            db,
            actor_id=actor_id,
            action="file.upload",
            target=str(record.id),
            request_id=request_id,
        )
    except Exception:
        # No commit was attempted, so deleting the freshly written object cannot
        # remove bytes referenced by a committed metadata row.
        await db.rollback()
        await _cleanup_uncommitted_upload(db, storage, stored.key, request_id)
        raise

    try:
        await db.commit()
    except Exception:
        # A failed commit acknowledgement is ambiguous: PostgreSQL may already be
        # durable. Never delete bytes directly here. A live-record recheck in the
        # operator cleanup path makes the durable intent safe for both outcomes.
        await db.rollback()
        await _record_cleanup_intent(
            db,
            storage,
            object_key=stored.key,
            file_id=None,
            reason="upload_commit_unknown",
            request_id=request_id,
        )
        raise
    return record


async def _cleanup_uncommitted_upload(
    db: AsyncSession,
    storage: StoragePort,
    key: str,
    request_id: str,
) -> None:
    """Delete bytes only after a transaction definitely did not commit."""
    try:
        await run_in_threadpool(storage.delete, key)
    except Exception:
        log.error(
            "file.upload_cleanup_failed",
            extra={"request_id": request_id, "fields": {"object_key": key}},
            exc_info=True,
        )
        await _record_cleanup_intent(
            db,
            storage,
            object_key=key,
            file_id=None,
            reason="upload_rollback",
            request_id=request_id,
        )


async def _record_cleanup_intent(
    db: AsyncSession,
    storage: StoragePort,
    *,
    object_key: str,
    file_id: int | None,
    reason: str,
    request_id: str,
) -> bool:
    """Commit an idempotent cleanup intent; never delete during recovery."""
    try:
        await db.execute(
            pg_insert(FileCleanupJob)
            .values(
                object_key=object_key,
                file_id=file_id,
                reason=reason,
                attempts=0,
            )
            .on_conflict_do_nothing(index_elements=[FileCleanupJob.object_key])
        )
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        _journal_failure(storage, object_key=object_key, file_id=file_id, request_id=request_id)
        return False


def _journal_failure(
    storage: StoragePort,
    *,
    object_key: str,
    file_id: int | None,
    request_id: str,
) -> None:
    """Best-effort fallback evidence; the DB intent remains authoritative."""
    try:
        root = storage.root
        if file_id is None:
            record_failed_cleanup(root, object_key=object_key, request_id=request_id)
        else:
            record_uncertain_delete(
                root,
                object_key=object_key,
                file_id=file_id,
                request_id=request_id,
            )
    except Exception:
        log.critical(
            "file.cleanup_reconciliation_journal_failed",
            exc_info=True,
            extra={"request_id": request_id, "fields": {"object_key": object_key}},
        )


async def authorized_record(
    db: AsyncSession,
    *,
    file_id: int,
    actor_id: int,
    permissions: frozenset[str],
    action: str,
    request_id: str,
) -> FileRecord:
    """Fetch metadata, enforce object authorization and audit denied access."""
    record = (
        await db.execute(select(FileRecord).where(FileRecord.id == file_id))
    ).scalar_one_or_none()
    if record is None:
        await _audit_access_denied(db, actor_id=actor_id, file_id=file_id, request_id=request_id)
        raise AppError(ErrorCode.NOT_FOUND, 404)
    try:
        require_file_action(
            owner_id=record.owner_id,
            actor_id=actor_id,
            permissions=permissions,
            action=action,
        )
    except AppError:
        await _audit_access_denied(db, actor_id=actor_id, file_id=file_id, request_id=request_id)
        raise
    return record


async def _audit_access_denied(
    db: AsyncSession,
    *,
    actor_id: int,
    file_id: int,
    request_id: str,
) -> None:
    """Trace denied/missing file access without leaking existence to callers."""
    try:
        await record_audit(
            db,
            actor_id=actor_id,
            action="file.access_denied",
            target=f"file:{file_id}",
            request_id=request_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        log.error("file.access_denied_audit_failed", exc_info=True)


async def delete_file(
    db: AsyncSession,
    storage: StoragePort,
    *,
    file_id: int,
    actor_id: int,
    permissions: frozenset[str],
    request_id: str,
) -> None:
    """Atomically delete metadata/audit and persist a durable cleanup intent.

    No database row lock is held while filesystem IO runs. Failure to delete the
    object leaves the committed intent for an explicit operator retry.
    """
    record = await authorized_record(
        db,
        file_id=file_id,
        actor_id=actor_id,
        permissions=permissions,
        action="delete",
        request_id=request_id,
    )
    try:
        result = await db.execute(
            delete(FileRecord).where(FileRecord.id == file_id).returning(FileRecord.id)
        )
        if result.scalar_one_or_none() is None:
            await db.rollback()
            await _audit_access_denied(
                db,
                actor_id=actor_id,
                file_id=file_id,
                request_id=request_id,
            )
            raise AppError(ErrorCode.NOT_FOUND, 404)
        db.add(
            FileCleanupJob(
                object_key=record.object_key,
                file_id=file_id,
                reason="delete",
            )
        )
        await record_audit(
            db,
            actor_id=actor_id,
            action="file.delete",
            target=str(file_id),
            request_id=request_id,
        )
        await db.commit()
    except AppError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        _journal_failure(
            storage, object_key=record.object_key, file_id=file_id, request_id=request_id
        )
        raise
    try:
        await run_in_threadpool(storage.delete, record.object_key)
    except Exception:
        log.error(
            "file.cleanup_deferred",
            extra={
                "event": "file.cleanup_deferred",
                "fields": {"file_id": file_id},
                "request_id": request_id,
            },
            exc_info=True,
        )
        return
    try:
        await db.execute(
            delete(FileCleanupJob).where(FileCleanupJob.object_key == record.object_key)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        log.error("file.cleanup_ack_failed", exc_info=True)


async def retry_file_cleanup(
    db: AsyncSession,
    storage: StoragePort,
    *,
    limit: int = 100,
    lease_seconds: int = CLEANUP_LEASE_SECONDS,
) -> tuple[int, int]:
    """Retry durable deletions using PostgreSQL lease claims and live rechecks.

    The claim commits before filesystem IO, so no transaction or row lock spans a
    blocking storage call. Expired leases can be taken over by another operator.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if not 10 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 10 and 3600")
    completed = failed = 0
    seen: set[int] = set()
    for _ in range(limit):
        now = datetime.now(timezone.utc)
        candidates = (
            (
                await db.execute(
                    select(FileCleanupJob.id)
                    .where(
                        FileCleanupJob.id.not_in(seen),
                        or_(
                            FileCleanupJob.lease_until.is_(None),
                            FileCleanupJob.lease_until < now,
                        ),
                    )
                    .order_by(FileCleanupJob.created_at, FileCleanupJob.id)
                    .limit(max(10, limit - completed - failed))
                )
            )
            .scalars()
            .all()
        )
        claimed = None
        token = secrets.token_hex(16)
        for job_id in candidates:
            seen.add(job_id)
            claimed = (
                await db.execute(
                    update(FileCleanupJob)
                    .where(
                        FileCleanupJob.id == job_id,
                        or_(
                            FileCleanupJob.lease_until.is_(None),
                            FileCleanupJob.lease_until < now,
                        ),
                    )
                    .values(
                        lease_token=token,
                        lease_until=now + timedelta(seconds=lease_seconds),
                        attempts=FileCleanupJob.attempts + 1,
                        last_error=None,
                    )
                    .returning(
                        FileCleanupJob.id,
                        FileCleanupJob.object_key,
                        FileCleanupJob.file_id,
                    )
                )
            ).one_or_none()
            await db.commit()
            if claimed is not None:
                break
        if claimed is None:
            await db.rollback()
            break
        job_id, object_key, file_id = claimed
        try:
            live_id = (
                await db.execute(select(FileRecord.id).where(FileRecord.object_key == object_key))
            ).scalar_one_or_none()
            if live_id is not None:
                await db.execute(
                    delete(FileCleanupJob).where(
                        FileCleanupJob.id == job_id,
                        FileCleanupJob.lease_token == token,
                    )
                )
                await db.commit()
                completed += 1
                continue
            await run_in_threadpool(storage.delete, object_key)
        except Exception as exc:
            await db.rollback()
            try:
                await db.execute(
                    update(FileCleanupJob)
                    .where(
                        FileCleanupJob.id == job_id,
                        FileCleanupJob.lease_token == token,
                    )
                    .values(
                        lease_token=None,
                        lease_until=None,
                        last_error=type(exc).__name__[:255],
                    )
                )
                await db.commit()
            except Exception:
                await db.rollback()
                log.error("file.cleanup_lease_release_failed", exc_info=True)
            failed += 1
            continue
        try:
            await db.execute(
                delete(FileCleanupJob).where(
                    FileCleanupJob.id == job_id,
                    FileCleanupJob.lease_token == token,
                )
            )
            await db.commit()
            completed += 1
        except Exception:
            await db.rollback()
            log.error("file.cleanup_ack_failed", exc_info=True)
    return completed, failed


async def scan_orphan_objects(
    db: AsyncSession,
    storage: StoragePort,
    *,
    grace_seconds: int = 3600,
    apply: bool = False,
) -> tuple[int, int, int]:
    """Report or enqueue orphan objects older than the configured grace period.

    This is an explicit operator operation, never a scheduled worker. ``apply``
    only writes durable intents; physical deletion still goes through retry.
    """
    if not 60 <= grace_seconds <= 30 * 24 * 3600:
        raise ValueError("grace_seconds must be between 60 and 2592000")
    now = datetime.now(timezone.utc)
    keys = await run_in_threadpool(storage.iter_object_keys)
    live = set((await db.execute(select(FileRecord.object_key))).scalars().all())
    pending = set((await db.execute(select(FileCleanupJob.object_key))).scalars().all())
    orphans: list[str] = []
    for key in keys:
        if key in live or key in pending:
            continue
        try:
            modified = await run_in_threadpool(storage.modified_at, key)
        except (OSError, ValueError):
            # The object may disappear between directory enumeration and stat.
            # A transient storage error must not abort all unrelated candidates.
            log.warning(
                "file.orphan_stat_failed",
                extra={"fields": {"object_key": key}},
                exc_info=True,
            )
            continue
        if now - modified < timedelta(seconds=grace_seconds):
            continue
        orphans.append(key)
    queued = 0
    if apply and orphans:
        try:
            result = await db.execute(
                pg_insert(FileCleanupJob)
                .values(
                    [
                        {
                            "object_key": key,
                            "file_id": None,
                            "reason": "orphan_scan",
                            "attempts": 0,
                        }
                        for key in orphans
                    ]
                )
                .on_conflict_do_nothing(index_elements=[FileCleanupJob.object_key])
                .returning(FileCleanupJob.id)
            )
            await db.commit()
            # ON CONFLICT may skip rows claimed by a concurrent scanner. Report
            # the number actually inserted, not merely the number considered.
            queued = len(result.scalars().all())
        except Exception:
            await db.rollback()
            raise
    return len(keys), len(orphans), queued


async def record_download(
    db: AsyncSession,
    *,
    file_id: int,
    actor_id: int,
    request_id: str,
) -> None:
    """Record successful server-side content preparation, not client receipt."""
    try:
        await record_audit(
            db,
            actor_id=actor_id,
            action="file.content_prepared",
            target=str(file_id),
            request_id=request_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
