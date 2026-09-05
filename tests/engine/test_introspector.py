"""Tests for the Introspector caching wrapper."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.events import EventBus, SchemaRefreshed
from teridex_core.models.connection import Dsn
from teridex_core.models.schema import ForeignKey, Index, SchemaSnapshot, TableColumn
from teridex_engine.introspector import Introspector

if TYPE_CHECKING:
    from teridex_core.protocols.adapter import DatabaseAdapter


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self.last_lazy: bool | None = None

    async def introspect(self, *, lazy: bool = False) -> SchemaSnapshot:
        self.calls += 1
        self.last_lazy = lazy
        return SchemaSnapshot(connection_id=f"conn-{self.calls}")

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        return []

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        return []

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        return []


async def _drain() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_snapshot_is_cached_until_invalidated() -> None:
    adapter = _FakeAdapter()
    intro = Introspector(cast("DatabaseAdapter", adapter), EventBus())

    first = await intro.snapshot()
    second = await intro.snapshot()
    assert first is second
    assert adapter.calls == 1

    intro.invalidate()
    third = await intro.snapshot()
    assert third is not first
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_refresh_forces_a_new_snapshot() -> None:
    adapter = _FakeAdapter()
    intro = Introspector(cast("DatabaseAdapter", adapter), EventBus())

    first = await intro.snapshot()
    refreshed = await intro.refresh()
    assert refreshed is not first
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_schema_refreshed_published_once_per_introspect() -> None:
    bus = EventBus()
    received: list[SchemaRefreshed] = []

    async def on_refresh(ev: SchemaRefreshed) -> None:
        received.append(ev)

    bus.subscribe(SchemaRefreshed, on_refresh)
    adapter = _FakeAdapter()
    intro = Introspector(cast("DatabaseAdapter", adapter), bus)

    await intro.snapshot()  # introspects -> publishes
    await intro.snapshot()  # cache hit -> no publish
    await intro.refresh()  # introspects -> publishes

    await _drain()
    assert len(received) == 2
    await bus.close()


@pytest.mark.asyncio
async def test_snapshot_and_refresh_support_lazy() -> None:
    adapter = _FakeAdapter()
    intro = Introspector(cast("DatabaseAdapter", adapter), EventBus())

    await intro.snapshot(lazy=True)
    assert adapter.last_lazy is True

    await intro.refresh(lazy=False)
    assert adapter.last_lazy is False


@pytest.mark.asyncio
async def test_lazy_cache_does_not_satisfy_a_full_snapshot() -> None:
    """A lazy snapshot holds no columns, so it must not answer a full request.

    The cache used to key on presence alone: once a lazy snapshot was taken
    (which is what the TUI's schema refresh does), every later
    ``snapshot(lazy=False)`` — including one from a plugin handed the
    introspector as a service — silently got back an empty schema.
    """
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    try:
        handle = await adapter.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        async for _ in await adapter.stream(handle):
            pass

        introspector = Introspector(adapter, bus)

        lazy = await introspector.snapshot(lazy=True)
        assert lazy.schemas["main"][0].columns == [], "precondition: lazy skips columns"

        full = await introspector.snapshot(lazy=False)
        assert [c.name for c in full.schemas["main"][0].columns] == ["id", "name"]

        # ...and the full snapshot is now cached, so a lazy request reuses it
        # rather than throwing away work.
        again = await introspector.snapshot(lazy=True)
        assert again is full
    finally:
        await bus.close()
        await adapter.close()
