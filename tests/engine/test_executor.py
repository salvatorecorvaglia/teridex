from __future__ import annotations

import asyncio

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.events import EventBus, QueryCompleted, QueryStarted
from teridex_core.models.connection import Dsn
from teridex_engine.executor import QueryExecutor


@pytest.mark.asyncio
async def test_executor_emits_lifecycle_events() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    starts: list[QueryStarted] = []
    completes: list[QueryCompleted] = []
    bus.subscribe(QueryStarted, lambda e: _append(starts, e))  # type: ignore[arg-type]
    bus.subscribe(QueryCompleted, lambda e: _append(completes, e))  # type: ignore[arg-type]

    executor = QueryExecutor(adapter, bus)
    run = await executor.run("SELECT 1 AS a")
    async for _ in run.rows:
        pass
    for _ in range(20):
        await asyncio.sleep(0)
        if starts and completes:
            break
    assert starts
    assert completes
    assert completes[0].rows == 1
    await bus.close()
    await adapter.close()


async def _append(target: list, ev: object) -> None:  # type: ignore[type-arg]
    target.append(ev)
