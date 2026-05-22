from __future__ import annotations

import asyncio

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.errors import QueryCancelledError, QueryError
from teridex_core.events import (
    EventBus,
    QueryCancelled,
    QueryCompleted,
    QueryFailed,
    QueryStarted,
)
from teridex_core.logging import _request_context  # type: ignore[attr-defined]
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


@pytest.mark.asyncio
async def test_executor_cancellation_emits_cancelled_event() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    cancelled: list[QueryCancelled] = []
    bus.subscribe(QueryCancelled, lambda e: _append(cancelled, e))  # type: ignore[arg-type]

    executor = QueryExecutor(adapter, bus)
    run = await executor.run("SELECT 1 AS a")
    await executor.cancel(run)
    with pytest.raises(QueryCancelledError):
        async for _ in run.rows:
            pass

    for _ in range(20):
        await asyncio.sleep(0)
        if cancelled:
            break
    assert cancelled
    assert cancelled[0].query_id == run.query_id
    # The wrapper's finally{} must still clear the logging context.
    assert _request_context.get() in (None, {})
    await bus.close()
    await adapter.close()


@pytest.mark.asyncio
async def test_executor_publishes_failed_on_bad_sql() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    failed: list[QueryFailed] = []
    bus.subscribe(QueryFailed, lambda e: _append(failed, e))  # type: ignore[arg-type]

    executor = QueryExecutor(adapter, bus)
    with pytest.raises(QueryError):
        await executor.run("SELECT * FROM table_that_does_not_exist")

    for _ in range(20):
        await asyncio.sleep(0)
        if failed:
            break
    assert failed
    # A failed run must not strand the logging context bound by run().
    assert _request_context.get() in (None, {})
    await bus.close()
    await adapter.close()


@pytest.mark.asyncio
async def test_executor_binds_query_id_into_logging_context() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    executor = QueryExecutor(adapter, bus)

    seen_ctx: dict[str, str] = {}
    run = await executor.run("SELECT 1")

    # bind_context fires before the first batch is yielded; capture the
    # contextvar mid-stream by reading it inside the iteration loop.
    async for _ in run.rows:
        ctx = _request_context.get() or {}
        seen_ctx.update(ctx)

    # After the stream exits the executor's finally{} should have cleared
    # the context.
    assert _request_context.get() in (None, {})
    assert seen_ctx.get("query_id") == run.query_id
    assert seen_ctx.get("adapter") == "sqlite"

    await bus.close()
    await adapter.close()
