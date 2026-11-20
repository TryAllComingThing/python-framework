"""Best-effort local reconciliation journals for infrastructure failures.

The journal is fallback evidence only. PostgreSQL cleanup intents are the
authoritative recovery mechanism; journals never trigger automatic deletion.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path


def _ensure_root(root: Path) -> None:
    if root.is_symlink():
        raise ValueError("journal root must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("journal root must be a real directory")


def _open_root(root: Path) -> int:
    _ensure_root(root)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("journal root must be a directory")
    return descriptor


def _open_or_create_directory(root_fd: int, directory_name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(directory_name, flags, dir_fd=root_fd)
    except FileNotFoundError:
        os.mkdir(directory_name, mode=0o700, dir_fd=root_fd)
        return os.open(directory_name, flags, dir_fd=root_fd)


def _write_journal(root: Path, directory_name: str, payload: dict[str, object]) -> Path:
    filename = secrets.token_hex(16) + ".json"
    root_fd = _open_root(root)
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = _open_or_create_directory(root_fd, directory_name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(filename, flags, 0o600, dir_fd=directory_fd)
        with os.fdopen(file_fd, "w", encoding="utf-8") as output:
            file_fd = -1
            json.dump({**payload, "observed_at": datetime.now(timezone.utc).isoformat()}, output)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(directory_fd)
        os.fsync(root_fd)
    except BaseException:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            try:
                os.unlink(filename, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(root_fd)
    return root / directory_name / filename


def record_failed_cleanup(storage_root: Path, *, object_key: str, request_id: str) -> Path:
    """Persist fallback evidence for an upload cleanup/reconciliation candidate."""
    return _write_journal(
        storage_root,
        ".upload-cleanup-pending",
        {
            "kind": "upload_commit_or_cleanup_unknown",
            "object_key": object_key,
            "request_id": request_id,
            "outcome": "unknown",
        },
    )


def record_uncertain_delete(
    storage_root: Path,
    *,
    object_key: str,
    file_id: int,
    request_id: str,
) -> Path:
    """Persist fallback evidence for an ambiguous delete commit."""
    return _write_journal(
        storage_root,
        ".delete-commit-unknown",
        {
            "kind": "delete_commit_unknown",
            "object_key": object_key,
            "file_id": file_id,
            "request_id": request_id,
            "outcome": "unknown",
        },
    )
