from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.errors import QueryCancelledError, QueryError, QueryTimeoutError
from teridex_core.events import (
    EventBus,
    QueryCancelled,
    QueryCompleted,
    QueryFailed,
    QueryStarted,
)
from teridex_core.logging import _request_context, bind_context, clear_context
from teridex_core.models.connection import Dsn
from teridex_core.models.query import QueryHandle, QueryStatus
from teridex_core.models.result import Column, ResultBatch
from teridex_engine.executor import QueryExecutor

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.mark.asyncio
async def test_executor_emits_lifecycle_events() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    starts: list[QueryStarted] = []
    completes: list[QueryCompleted] = []
    bus.subscribe(QueryStarted, lambda e: _append(starts, e))
    bus.subscribe(QueryCompleted, lambda e: _append(completes, e))

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
    bus.subscribe(QueryCancelled, lambda e: _append(cancelled, e))

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
    bus.subscribe(QueryFailed, lambda e: _append(failed, e))

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


@pytest.mark.asyncio
async def test_task_cancellation_still_publishes_a_terminal_event() -> None:
    """A cancelled *task* must not strand the UI on "running".

    ``asyncio.CancelledError`` is a ``BaseException``, so a bare
    ``except Exception`` in the stream wrapper would let it through without
    ever publishing a lifecycle-terminal event. The cancellation has to land
    while the adapter's stream is awaiting — that is the window a slow query
    spends nearly all of its time in.
    """
    bus = EventBus()
    cancelled: list[QueryCancelled] = []
    bus.subscribe(QueryCancelled, lambda e: _append(cancelled, e))

    executor = QueryExecutor(_SlowAdapter(), bus)
    run = await executor.run("SELECT 1 AS a")

    async def _consume() -> None:
        async for _ in run.rows:
            pass

    task = asyncio.create_task(_consume())
    for _ in range(50):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(20):
        await asyncio.sleep(0)
        if cancelled:
            break
    assert cancelled, "task cancellation published no terminal event"
    assert cancelled[0].query_id == run.query_id
    await bus.close()


@pytest.mark.asyncio
async def test_abandoned_stream_reports_cancelled_not_completed() -> None:
    """Breaking out early and closing must not look like a successful run."""
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    await _exec(adapter, "CREATE TABLE t (id INTEGER)")
    for i in range(5):
        await _exec(adapter, f"INSERT INTO t VALUES ({i})")

    bus = EventBus()
    completed: list[QueryCompleted] = []
    cancelled: list[QueryCancelled] = []
    bus.subscribe(QueryCompleted, lambda e: _append(completed, e))
    bus.subscribe(QueryCancelled, lambda e: _append(cancelled, e))

    executor = QueryExecutor(adapter, bus)
    run = await executor.run("SELECT id FROM t", batch_size=1)
    async for _ in run.rows:
        break
    await run.aclose()

    for _ in range(20):
        await asyncio.sleep(0)
        if cancelled:
            break
    assert cancelled, "an abandoned stream published no cancellation"
    assert not completed, "a partial read was reported as a completed query"
    assert run.status is QueryStatus.CANCELLED
    await bus.close()
    await adapter.close()


@pytest.mark.asyncio
async def test_aclose_is_idempotent_after_full_consumption() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    cancelled: list[QueryCancelled] = []
    bus.subscribe(QueryCancelled, lambda e: _append(cancelled, e))

    executor = QueryExecutor(adapter, bus)
    run = await executor.run("SELECT 1 AS a")
    async for _ in run.rows:
        pass
    await run.aclose()
    await run.aclose()

    for _ in range(20):
        await asyncio.sleep(0)
    assert not cancelled, "closing an exhausted stream must not look like a cancel"
    await bus.close()
    await adapter.close()


@pytest.mark.asyncio
async def test_run_restores_rather_than_wipes_surrounding_log_context() -> None:
    """The executor must not clobber context bound by its caller."""
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    executor = QueryExecutor(adapter, bus)

    bind_context(session_id="outer-session")
    run = await executor.run("SELECT 1 AS a")
    async for _ in run.rows:
        pass

    assert (_request_context.get() or {}).get("session_id") == "outer-session"
    assert "query_id" not in (_request_context.get() or {})
    clear_context()
    await bus.close()
    await adapter.close()


async def _exec(adapter: SQLiteAdapter, sql: str) -> None:
    handle = await adapter.execute(sql)
    async for _ in await adapter.stream(handle):
        pass


class _SlowAdapter:
    """Minimal adapter whose stream parks inside its own await."""

    name = "slow"

    def __init__(self) -> None:
        self.cancelled = False

    async def execute(self, sql: str, params: object = None) -> QueryHandle:
        handle = QueryHandle(connection_id="slow", sql=sql)
        handle.mark_running()
        return handle

    async def stream(
        self, handle: QueryHandle, *, batch_size: int = 1000
    ) -> AsyncIterator[ResultBatch]:
        async def _gen() -> AsyncIterator[ResultBatch]:
            yield ResultBatch(columns=[Column(name="a")], rows=[(1,)])
            await asyncio.sleep(3600)  # never produces a second batch
            yield ResultBatch(columns=[Column(name="a")], rows=[], is_last=True)

        return _gen()

    async def cancel(self, handle: QueryHandle) -> None:
        self.cancelled = True


@pytest.mark.asyncio
async def test_timeout_aborts_the_run_and_cancels_the_query() -> None:
    """``engine.default_timeout_seconds`` must actually bound a run."""
    adapter = _SlowAdapter()
    bus = EventBus()
    failed: list[QueryFailed] = []
    bus.subscribe(QueryFailed, lambda e: _append(failed, e))

    executor = QueryExecutor(adapter, bus)
    run = await executor.run("SELECT 1 AS a", timeout=0.05)

    with pytest.raises(QueryTimeoutError):
        async for _ in run.rows:
            pass

    assert adapter.cancelled, "a timed-out query must be cancelled server-side"
    for _ in range(20):
        await asyncio.sleep(0)
        if failed:
            break
    assert failed, "a timed-out query published no failure event"
    assert failed[0].error_code == "teridex.query.timeout"
    await bus.close()


@pytest.mark.asyncio
async def test_timeout_of_zero_means_no_deadline() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    executor = QueryExecutor(adapter, bus)

    run = await executor.run("SELECT 1 AS a", timeout=0)
    rows = [batch async for batch in run.rows]

    assert sum(len(b.rows) for b in rows) == 1
    await bus.close()
    await adapter.close()


@pytest.mark.asyncio
async def test_a_fast_query_finishes_well_inside_its_timeout() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    executor = QueryExecutor(adapter, bus)

    run = await executor.run("SELECT 1 AS a", timeout=30)
    emitted = 0
    async for batch in run.rows:
        emitted += len(batch.rows)
    assert emitted == 1

    await bus.close()
    await adapter.close()


@pytest.mark.asyncio
async def test_aclose_finalizes_the_adapters_stream() -> None:
    """``QueryRun.aclose()`` must close the adapter's generator, not just the wrapper.

    The executor wraps the adapter's stream in ``_wrap()``. Closing only the
    wrapper left the adapter's generator suspended at its own ``yield``, so the
    driver cursor (and, on Postgres, the transaction around the server-side
    cursor) outlived the run — and the pool had already handed the connection
    to the next query by then.
    """
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    try:
        await _drain(adapter, "CREATE TABLE t (id INTEGER)")
        for i in range(20):
            await _drain(adapter, f"INSERT INTO t VALUES ({i})")

        executor = QueryExecutor(adapter, bus)
        run = await executor.run("SELECT id FROM t", batch_size=5)
        async for _ in run.rows:
            break  # abandon the stream early, exactly as the docstring allows
        assert adapter._cursors, "precondition: the cursor is still open mid-stream"

        await run.aclose()

        assert adapter._cursors == {}, "aclose() left the adapter's cursor open"
        assert adapter._cancel_flags == {}, "aclose() left the handle's cancel flag behind"
    finally:
        await bus.close()
        await adapter.close()


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    adapter = SQLiteAdapter()
    await adapter.connect(Dsn.parse("sqlite:///:memory:"))
    bus = EventBus()
    try:
        executor = QueryExecutor(adapter, bus)
        run = await executor.run("SELECT 1 AS a")
        await run.aclose()
        await run.aclose()  # must not raise
    finally:
        await bus.close()
        await adapter.close()


async def _drain(adapter: SQLiteAdapter, sql: str) -> None:
    handle = await adapter.execute(sql)
    async for _ in await adapter.stream(handle):
        pass
