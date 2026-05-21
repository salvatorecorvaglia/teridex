"""Shared adapter conformance suite.

Each adapter-specific test module instantiates the right fixture and the
same scenarios run uniformly. Keeps the matrix honest as adapters land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from teridex_core.errors import QueryCancelledError

if TYPE_CHECKING:
    from teridex_core.protocols.adapter import DatabaseAdapter


async def _drain(adapter: DatabaseAdapter, sql: str) -> list[tuple[object, ...]]:
    handle = await adapter.execute(sql)
    out: list[tuple[object, ...]] = []
    async for batch in await adapter.stream(handle):
        out.extend(batch.rows)
    return [r for r in out if r]


async def assert_connect_and_ping(adapter: DatabaseAdapter) -> None:
    assert await adapter.ping() is True


async def assert_create_insert_select(
    adapter: DatabaseAdapter,
    *,
    create_sql: str,
    insert_sql: str,
    select_sql: str,
    expected_rows: list[tuple[object, ...]],
) -> None:
    for stmt in (create_sql, insert_sql):
        await _drain(adapter, stmt)
    rows = await _drain(adapter, select_sql)
    assert rows == expected_rows


async def assert_introspect_includes(adapter: DatabaseAdapter, table_name: str) -> None:
    snap = await adapter.introspect()
    found = [obj for objs in snap.schemas.values() for obj in objs if obj.name == table_name]
    assert found, f"introspection did not find table {table_name!r}; got {sorted(snap.schemas)}"


async def assert_cancel_raises(adapter: DatabaseAdapter, sql: str) -> None:
    handle = await adapter.execute(sql)
    await adapter.cancel(handle)
    with pytest.raises(QueryCancelledError):
        async for _ in await adapter.stream(handle):
            pass
