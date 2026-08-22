from __future__ import annotations

import pytest

from teridex_core.models.connection import Dsn
from teridex_tui.session import is_in_memory, is_single_connection_dsn, share_in_memory_sqlite


@pytest.mark.parametrize(
    ("dsn_str", "expected"),
    [
        ("sqlite:///:memory:", True),
        ("sqlite://", True),
        ("sqlite:///./data.db", False),
        ("duckdb:///:memory:", True),
        ("duckdb://", True),
        ("duckdb:///./data.duckdb", False),
        ("postgres://localhost/db", False),
        ("mysql://localhost/db", False),
    ],
)
def test_is_in_memory(dsn_str: str, expected: bool) -> None:
    assert is_in_memory(Dsn.parse(dsn_str)) is expected


@pytest.mark.parametrize(
    ("dsn_str", "expected"),
    [
        ("duckdb:///:memory:", True),
        ("duckdb://", True),
        ("duckdb:///./data.duckdb", False),
        ("sqlite:///:memory:", False),  # sqlite has a shared-cache path instead
        ("postgres://localhost/db", False),
    ],
)
def test_is_single_connection_dsn(dsn_str: str, expected: bool) -> None:
    assert is_single_connection_dsn(Dsn.parse(dsn_str)) is expected


def test_share_in_memory_sqlite_rewrites_to_a_named_shared_cache_uri() -> None:
    dsn = Dsn.parse("sqlite:///:memory:")
    shared = share_in_memory_sqlite(dsn)
    assert shared.scheme == "sqlite"
    assert shared.database is not None
    assert shared.database.startswith("file:teridex-mem-")
    assert shared.params["mode"] == "memory"
    assert shared.params["cache"] == "shared"


def test_share_in_memory_sqlite_is_idempotent_across_calls() -> None:
    dsn = Dsn.parse("sqlite:///:memory:")
    first = share_in_memory_sqlite(dsn)
    second = share_in_memory_sqlite(dsn)
    # Each call mints a fresh unique name — different in-memory databases,
    # not the same one reused.
    assert first.database != second.database


def test_share_in_memory_sqlite_leaves_a_real_file_path_untouched() -> None:
    dsn = Dsn.parse("sqlite:///./data.db")
    assert share_in_memory_sqlite(dsn) == dsn


def test_share_in_memory_sqlite_leaves_non_sqlite_dsns_untouched() -> None:
    dsn = Dsn.parse("duckdb:///:memory:")
    assert share_in_memory_sqlite(dsn) == dsn
