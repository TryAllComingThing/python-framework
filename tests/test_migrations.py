from __future__ import annotations

from types import SimpleNamespace

import pytest

from migrations.preflight import assert_username_keys_unique


class FakeResult:
    def __init__(self, *, scalar: object = None, rows: list[object] | None = None) -> None:
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one(self) -> object:
        return self.scalar

    def all(self) -> list[object]:
        return self.rows


class FakeConnection:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = iter(results)

    def execute(self, statement: object) -> FakeResult:
        return next(self.results)


def test_username_preflight_skips_fresh_database() -> None:
    connection = FakeConnection([FakeResult(scalar=None)])

    assert_username_keys_unique(connection)  # type: ignore[arg-type]


def test_username_preflight_reports_case_insensitive_duplicates() -> None:
    duplicate = SimpleNamespace(username_key="alice", duplicate_count=2)
    connection = FakeConnection([FakeResult(scalar="sf_users"), FakeResult(rows=[duplicate])])

    with pytest.raises(RuntimeError, match=r"'alice' \(2\)"):
        assert_username_keys_unique(connection)  # type: ignore[arg-type]
