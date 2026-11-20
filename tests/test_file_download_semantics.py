from __future__ import annotations

import asyncio
import threading
from collections.abc import Generator
from typing import cast

import pytest
from starlette.concurrency import run_in_threadpool

from app.core.codes import ErrorCode
from app.core.errors import AppError
from app.modules.files.router import (
    _close_stream,
    _etag_matches,
    _parse_range,
    _SerializedStorageStream,
    _strong_etag_matches,
)


def test_if_none_match_accepts_weak_comparison_but_if_range_requires_strong() -> None:
    etag = '"abc123"'
    assert _etag_matches(f"W/{etag}", etag)
    assert _etag_matches(f'"other", {etag}', etag)
    assert _etag_matches("*", etag)
    assert _strong_etag_matches(etag, etag)
    assert not _strong_etag_matches(f"W/{etag}", etag)
    assert not _strong_etag_matches("*", etag)


def test_range_parser_handles_inclusive_and_suffix_ranges() -> None:
    assert _parse_range("bytes=2-5", 10) == (2, 5)
    assert _parse_range("bytes=5-", 10) == (5, 9)
    assert _parse_range("bytes=-3", 10) == (7, 9)
    assert _parse_range("bytes=0-999", 10) == (0, 9)


@pytest.mark.parametrize(
    "value",
    [
        "bytes=-0",
        "bytes=10-",
        "bytes=5-2",
        "bytes=0-1,3-4",
        "items=0-1",
        "bytes=" + "9" * 5000 + "-",
    ],
)
def test_range_parser_rejects_unsatisfiable_or_multi_range(value: str) -> None:
    with pytest.raises(AppError) as raised:
        _parse_range(value, 10)
    assert raised.value.code == str(ErrorCode.RANGE_NOT_SATISFIABLE)


async def test_stream_close_runs_in_worker_thread() -> None:
    caller_thread = threading.get_ident()
    closed_on: list[int] = []

    class Stream:
        def close(self) -> None:
            closed_on.append(threading.get_ident())

    await _close_stream(cast(Generator[bytes, None, None], Stream()))

    assert closed_on
    assert closed_on[0] != caller_thread


async def test_serialized_stream_close_waits_for_inflight_next() -> None:
    entered = threading.Event()
    release = threading.Event()
    closed: list[str] = []

    class Stream:
        def __next__(self) -> bytes:
            entered.set()
            assert release.wait(timeout=2)
            raise StopIteration

        def close(self) -> None:
            closed.append("closed")

    stream = _SerializedStorageStream(cast(Generator[bytes, None, None], Stream()))
    next_task = asyncio.create_task(run_in_threadpool(next, stream, None))
    assert await asyncio.to_thread(entered.wait, 2)

    close_task = asyncio.create_task(_close_stream(stream))
    await asyncio.sleep(0.05)
    assert closed == []

    release.set()
    assert await next_task is None
    await close_task
    assert closed == ["closed"]
