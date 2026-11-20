from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.infrastructure.storage import LocalStorage


def test_local_storage_put_get_range_and_iterator_close(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "objects", max_bytes=32)
    storage.initialize()
    stored = storage.put(b"0123456789", ".txt")

    assert b"".join(storage.iter_chunks(stored.key)) == b"0123456789"
    assert b"".join(storage.iter_chunks(stored.key, offset=2, length=4, chunk_size=2)) == b"2345"

    stream = storage.iter_chunks(stored.key, chunk_size=2)
    assert next(stream) == b"01"
    stream.close()


def test_local_storage_rejects_root_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "root-link"
    os.symlink(real, link)

    with pytest.raises(ValueError):
        LocalStorage(link).initialize()


def test_local_storage_rejects_object_symlink_and_ignores_in_scan(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "objects", max_bytes=32)
    storage.initialize()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    key = "a" * 40 + ".txt"
    os.symlink(outside, storage.root / key)

    assert storage.iter_object_keys() == []
    with pytest.raises((OSError, ValueError)):
        next(storage.iter_chunks(key))
    with pytest.raises(ValueError):
        storage.delete(key)
    with pytest.raises(ValueError):
        storage.modified_at(key)


@pytest.mark.parametrize("key", ["", "../x", "A" * 40, "a" * 39, "a" * 40 + ".bad-suffix"])
def test_local_storage_rejects_invalid_object_keys(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path / "objects", max_bytes=32)
    storage.initialize()
    with pytest.raises(ValueError):
        next(storage.iter_chunks(key))
