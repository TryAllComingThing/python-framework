from __future__ import annotations

import io
import struct
import zlib
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import Workbook


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack("!I", len(payload))
        + kind
        + payload
        + struct.pack("!I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def png_bytes() -> bytes:
    ihdr = struct.pack("!IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00\xff")
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def jpeg_bytes() -> bytes:
    # SOI, an empty APP0 segment, SOS with one entropy byte, EOI. This exercises
    # generic marker parsing without depending on an image codec.
    return b"\xff\xd8\xff\xe0\x00\x02\xff\xda\x00\x02\x00\xff\xd9"


def pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


def xlsx_bytes(*, formula: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["name", "value"])
    sheet.append(["demo", "=1+1" if formula else 1])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


@dataclass
class FakeResult:
    rows: Any = None

    def scalar_one_or_none(self) -> Any:
        return self.rows

    def one_or_none(self) -> Any:
        return self.rows

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> Any:
        return self.rows if self.rows is not None else []


class FakeDB:
    def __init__(self, *, commit_failures: int = 0, flush_error: Exception | None = None) -> None:
        self.commit_failures = commit_failures
        self.flush_error = flush_error
        self.added: list[Any] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.execute_count = 0
        self.statements: list[Any] = []

    def add(self, value: Any) -> None:
        if getattr(value, "id", None) is None:
            value.id = len(self.added) + 1
        self.added.append(value)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error

    async def commit(self) -> None:
        self.commit_count += 1
        if self.commit_failures:
            self.commit_failures -= 1
            raise RuntimeError("commit acknowledgement lost")

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def execute(self, statement: Any) -> FakeResult:
        self.execute_count += 1
        self.statements.append(statement)
        return FakeResult()


class SequenceDB(FakeDB):
    def __init__(self, results: list[FakeResult]) -> None:
        super().__init__()
        self.results = deque(results)

    async def execute(self, statement: Any) -> FakeResult:
        self.execute_count += 1
        self.statements.append(statement)
        if not self.results:
            return FakeResult()
        return self.results.popleft()


class FakeStorage:
    def __init__(self, root: Path, *, delete_error: Exception | None = None) -> None:
        self.root = root
        self.delete_error = delete_error
        self.deleted: list[str] = []
        self.puts: list[tuple[bytes, str]] = []

    def put(self, data: bytes, suffix: str = "") -> Any:
        from app.infrastructure.storage import StoredObject

        self.puts.append((data, suffix))
        return StoredObject("a" * 40 + suffix, len(data), "b" * 64)

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        if self.delete_error is not None:
            raise self.delete_error
