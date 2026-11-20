from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.files.models import FileCleanupJob, FileRecord
from app.modules.files.service import delete_file, retry_file_cleanup, scan_orphan_objects
from tests.helpers import FakeResult, FakeStorage, SequenceDB


async def test_cleanup_rechecks_live_record_before_delete(tmp_path: object) -> None:
    key = "a" * 40 + ".txt"
    db = SequenceDB(
        [
            FakeResult([7]),
            FakeResult((7, key, None)),
            FakeResult(99),
            FakeResult(),
        ]
    )
    storage = FakeStorage(tmp_path)  # type: ignore[arg-type]

    assert await retry_file_cleanup(db, storage, limit=1) == (1, 0)  # type: ignore[arg-type]
    assert storage.deleted == []
    assert db.execute_count == 4
    assert db.commit_count == 2


async def test_cleanup_storage_failure_releases_lease_for_retry(tmp_path: object) -> None:
    key = "a" * 40 + ".txt"
    db = SequenceDB(
        [
            FakeResult([8]),
            FakeResult((8, key, None)),
            FakeResult(None),
            FakeResult(),
        ]
    )
    storage = FakeStorage(tmp_path, delete_error=OSError("disk unavailable"))  # type: ignore[arg-type]

    assert await retry_file_cleanup(db, storage, limit=1) == (0, 1)  # type: ignore[arg-type]
    assert storage.deleted == [key]
    assert db.execute_count == 4
    assert db.commit_count == 2
    assert db.rollback_count == 1


async def test_orphan_scan_reports_actual_inserted_count(tmp_path: object) -> None:
    now = datetime.now(timezone.utc)
    keys = ["a" * 40 + ".txt", "b" * 40 + ".txt"]

    class ScanStorage(FakeStorage):
        def iter_object_keys(self) -> list[str]:
            return keys

        def modified_at(self, key: str) -> datetime:
            return now - timedelta(hours=2)

    db = SequenceDB(
        [
            FakeResult([]),
            FakeResult([]),
            FakeResult([1]),
        ]
    )
    storage = ScanStorage(tmp_path)  # type: ignore[arg-type]

    assert await scan_orphan_objects(db, storage, apply=True) == (2, 2, 1)  # type: ignore[arg-type]


async def test_orphan_scan_skips_object_that_disappears_during_stat(tmp_path: object) -> None:
    key = "a" * 40 + ".txt"

    class DisappearingStorage(FakeStorage):
        def iter_object_keys(self) -> list[str]:
            return [key]

        def modified_at(self, object_key: str) -> datetime:
            raise FileNotFoundError(object_key)

    db = SequenceDB([FakeResult([]), FakeResult([])])
    storage = DisappearingStorage(tmp_path)  # type: ignore[arg-type]

    assert await scan_orphan_objects(db, storage) == (1, 0, 0)  # type: ignore[arg-type]


@pytest.mark.parametrize("grace_seconds", [0, 59, 30 * 24 * 3600 + 1])
async def test_orphan_scan_rejects_unsafe_grace_period(
    tmp_path: object,
    grace_seconds: int,
) -> None:
    storage = FakeStorage(tmp_path)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await scan_orphan_objects(
            FakeStorage.__new__(SequenceDB),  # type: ignore[arg-type]
            storage,  # type: ignore[arg-type]
            grace_seconds=grace_seconds,
        )


async def test_delete_file_reuses_authorization_and_commits_cleanup_intent(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "a" * 40 + ".txt"
    record = FileRecord(
        id=5,
        owner_id=7,
        object_key=key,
        original_name="notes.txt",
        content_type="text/plain",
        size=3,
        sha256="b" * 64,
    )
    db = SequenceDB([FakeResult(record), FakeResult(5), FakeResult()])
    storage = FakeStorage(tmp_path)  # type: ignore[arg-type]
    audits: list[str] = []

    async def audit(*args: object, **kwargs: object) -> None:
        audits.append(str(kwargs["action"]))

    monkeypatch.setattr("app.modules.files.service.record_audit", audit)

    await delete_file(
        db,  # type: ignore[arg-type]
        storage,  # type: ignore[arg-type]
        file_id=5,
        actor_id=7,
        permissions=frozenset({"file:delete"}),
        request_id="req-delete",
    )

    assert storage.deleted == [key]
    assert db.commit_count == 2
    assert db.rollback_count == 0
    assert audits == ["file.delete"]
    job = next(item for item in db.added if isinstance(item, FileCleanupJob))
    assert job.object_key == key
    assert job.reason == "delete"
