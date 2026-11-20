from __future__ import annotations

import pytest

from app.core.codes import ErrorCode
from app.core.errors import AppError
from app.infrastructure.malware import MalwareScannerUnavailableError
from app.modules.files import service as file_service
from tests.helpers import FakeDB, FakeStorage, png_bytes


@pytest.fixture
def allow_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(file_service, "record_audit", noop)


async def test_upload_flush_failure_cleans_uncommitted_object(
    tmp_path: object,
    allow_audit: None,
) -> None:
    db = FakeDB(flush_error=RuntimeError("flush failed"))
    storage = FakeStorage(tmp_path, delete_error=None)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="flush failed"):
        await file_service.upload_file(
            db,  # type: ignore[arg-type]
            storage,  # type: ignore[arg-type]
            actor_id=1,
            permissions=frozenset({"file:upload"}),
            filename="image.png",
            data=png_bytes(),
            request_id="req-upload-flush",
        )

    assert storage.deleted == ["a" * 40 + ".png"]
    assert db.execute_count == 0
    assert db.rollback_count == 1


async def test_upload_commit_unknown_never_deletes_bytes_directly(
    tmp_path: object,
    allow_audit: None,
) -> None:
    db = FakeDB(commit_failures=1)
    storage = FakeStorage(tmp_path)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="commit acknowledgement lost"):
        await file_service.upload_file(
            db,  # type: ignore[arg-type]
            storage,  # type: ignore[arg-type]
            actor_id=1,
            permissions=frozenset({"file:upload"}),
            filename="image.png",
            data=png_bytes(),
            request_id="req-upload-commit",
        )

    assert storage.deleted == []
    assert db.execute_count == 1
    assert db.commit_count == 2
    assert db.rollback_count == 1


async def test_upload_size_limit_is_payload_too_large() -> None:
    db = FakeDB()
    storage = FakeStorage.__new__(FakeStorage)
    with pytest.raises(AppError) as raised:
        await file_service.upload_file(
            db,  # type: ignore[arg-type]
            storage,  # type: ignore[arg-type]
            actor_id=1,
            permissions=frozenset({"file:upload"}),
            filename="image.png",
            data=png_bytes(),
            request_id="req-size",
            max_bytes=8,
        )
    assert raised.value.code == str(ErrorCode.PAYLOAD_TOO_LARGE)
    assert raised.value.status_code == 413


async def test_scanner_unavailable_is_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise MalwareScannerUnavailableError("offline")

    monkeypatch.setattr(file_service, "scan_with_clamd", unavailable)
    db = FakeDB()
    storage = FakeStorage.__new__(FakeStorage)
    with pytest.raises(AppError) as raised:
        await file_service.upload_file(
            db,  # type: ignore[arg-type]
            storage,  # type: ignore[arg-type]
            actor_id=1,
            permissions=frozenset({"file:upload"}),
            filename="image.png",
            data=png_bytes(),
            request_id="req-scan",
            scan_enabled=True,
        )
    assert raised.value.code == str(ErrorCode.SERVICE_UNAVAILABLE)
    assert raised.value.status_code == 503


async def test_upload_requires_explicit_permission() -> None:
    db = FakeDB()
    storage = FakeStorage.__new__(FakeStorage)
    with pytest.raises(AppError) as raised:
        await file_service.upload_file(
            db,  # type: ignore[arg-type]
            storage,  # type: ignore[arg-type]
            actor_id=1,
            permissions=frozenset(),
            filename="image.png",
            data=png_bytes(),
            request_id="req-denied",
        )
    assert raised.value.code == str(ErrorCode.FORBIDDEN)


async def test_upload_success_commits_metadata_and_audit(
    tmp_path: object,
    allow_audit: None,
) -> None:
    db = FakeDB()
    storage = FakeStorage(tmp_path)  # type: ignore[arg-type]

    record = await file_service.upload_file(
        db,  # type: ignore[arg-type]
        storage,  # type: ignore[arg-type]
        actor_id=7,
        permissions=frozenset({"file:upload"}),
        filename="image.png",
        data=png_bytes(),
        request_id="req-upload-success",
    )

    assert record.id == 1
    assert record.owner_id == 7
    assert record.object_key == "a" * 40 + ".png"
    assert db.commit_count == 1
    assert db.rollback_count == 0
