"""Storage port and symlink-safe local adapter.

Callers must authorize every object key. The local adapter only deletes or reads
objects that pass the repository's generated-key syntax and never follows object
symlinks. The configured root itself must not be a symlink.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

_OBJECT_KEY = re.compile(r"[0-9a-f]{40}(?:\.[a-z0-9]{1,12})?")


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str


class StoragePort(Protocol):
    root: Path

    def initialize(self) -> None:
        """Ensure the private storage root exists and is not a symlink."""
        ...

    def put(self, data: bytes, suffix: str = "") -> StoredObject:
        """Persist bytes and return generated metadata."""
        ...

    def delete(self, key: str) -> None:
        """Delete one generated object key; missing objects are ignored."""
        ...

    def iter_chunks(
        self,
        key: str,
        *,
        chunk_size: int = 64 * 1024,
        offset: int = 0,
        length: int | None = None,
    ) -> Generator[bytes, None, None]:
        """Yield bounded chunks from a generated object key."""
        ...

    def iter_object_keys(self) -> list[str]:
        """Return regular, non-symlink object keys under the private root."""
        ...

    def modified_at(self, key: str) -> datetime:
        """Return the modification time for a regular, non-symlink object."""
        ...


class LocalStorage:
    """Private local object store with explicit root and object symlink rejection."""

    def __init__(self, root: Path, max_bytes: int = 10_000_000) -> None:
        self.root = Path(root).expanduser().absolute()
        self.max_bytes = max_bytes

    def initialize(self) -> None:
        """Create/validate the configured root without following symlinks."""
        self._ensure_root()

    def _ensure_root(self) -> None:
        if self.root.exists() or self.root.is_symlink():
            if self.root.is_symlink():
                raise ValueError("storage root must not be a symlink")
            if not self.root.is_dir():
                raise ValueError("storage root must be a directory")
            return
        self.root.mkdir(mode=0o700, parents=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("storage root must be a real directory")

    @contextmanager
    def _root_fd(self) -> Iterator[int]:
        self._ensure_root()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.root, flags)
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise ValueError("storage root must be a directory")
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key or key.count(".") > 1 or key.startswith(".") or not _OBJECT_KEY.fullmatch(key):
            raise ValueError("invalid object key")

    @staticmethod
    def _validate_suffix(suffix: str) -> None:
        if suffix and (not suffix.startswith(".") or not suffix[1:].isalnum()):
            raise ValueError("invalid suffix")

    def put(self, data: bytes, suffix: str = "") -> StoredObject:
        """Persist bytes with file and directory fsync before returning.

        Raises ``ValueError`` for invalid size/suffix and ``OSError`` for storage
        failures. A failed create/write is removed before the exception escapes.
        """
        if not data or len(data) > self.max_bytes:
            raise ValueError("invalid object size")
        self._validate_suffix(suffix)
        key = secrets.token_hex(20) + suffix.lower()
        self._validate_key(key)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        with self._root_fd() as root_fd:
            descriptor = os.open(key, flags, 0o600, dir_fd=root_fd)
            created = True
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.fsync(root_fd)
            except BaseException:
                if created:
                    try:
                        os.unlink(key, dir_fd=root_fd)
                    except FileNotFoundError:
                        pass
                raise
        return StoredObject(key, len(data), hashlib.sha256(data).hexdigest())

    def iter_chunks(
        self,
        key: str,
        *,
        chunk_size: int = 64 * 1024,
        offset: int = 0,
        length: int | None = None,
    ) -> Generator[bytes, None, None]:
        """Yield bounded chunks from an object without following symlinks.

        The caller must close or exhaust the iterator. Raises ``ValueError`` for
        invalid range/key parameters and ``OSError`` for storage failures.
        """
        if not 1 <= chunk_size <= 1024 * 1024:
            raise ValueError("invalid chunk size")
        if offset < 0 or (length is not None and length < 0):
            raise ValueError("invalid object range")
        self._validate_key(key)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with self._root_fd() as root_fd:
            descriptor = os.open(key, flags, dir_fd=root_fd)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("stored object is not a regular file")
                if info.st_size > self.max_bytes or offset > info.st_size:
                    raise ValueError("stored object exceeds size limit")
                os.lseek(descriptor, offset, os.SEEK_SET)
                remaining = (
                    info.st_size - offset if length is None else min(length, info.st_size - offset)
                )
                with os.fdopen(descriptor, "rb") as source:
                    descriptor = -1
                    while remaining > 0:
                        chunk = source.read(min(chunk_size, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

    def delete(self, key: str) -> None:
        """Delete one generated object without following symlinks.

        A symlink occupying the object key is rejected rather than followed.
        Missing objects are treated as already deleted.
        """
        self._validate_key(key)
        with self._root_fd() as root_fd:
            try:
                info = os.stat(key, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("symlink object not allowed")
            os.unlink(key, dir_fd=root_fd)
            os.fsync(root_fd)

    def iter_object_keys(self) -> list[str]:
        """Return regular object-like keys; symlinks and directories are ignored."""
        keys: list[str] = []
        with self._root_fd() as root_fd, os.scandir(root_fd) as entries:
            for entry in entries:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                if _OBJECT_KEY.fullmatch(entry.name):
                    keys.append(entry.name)
        return sorted(keys)

    def modified_at(self, key: str) -> datetime:
        """Return an object's mtime without following symlinks."""
        self._validate_key(key)
        with self._root_fd() as root_fd:
            info = os.stat(key, dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("stored object is not a regular file")
        return datetime.fromtimestamp(info.st_mtime, tz=timezone.utc)
