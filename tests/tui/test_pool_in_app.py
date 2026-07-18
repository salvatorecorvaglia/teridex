"""TUI wires a ConnectionPool into the app and uses it for query execution."""

from __future__ import annotations

import asyncio

import pytest

textual = pytest.importorskip("textual")

from teridex_core.config import TeridexConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_engine.executor import QueryExecutor  # noqa: E402
from teridex_engine.pool import ConnectionPool  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402


@pytest.mark.asyncio
async def test_connect_populates_pool() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert isinstance(app.state.pool, ConnectionPool)
        assert app.state.adapter is not None
        
        # Verify in-memory database connection sharing:
        # Introspector adapter and pool adapter are the exact same instance.
        async with app.state.pool.acquire() as pooled_adapter:
            assert app.state.adapter is pooled_adapter


@pytest.mark.asyncio
async def test_pool_serves_two_concurrent_queries() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        pool = app.state.pool
        assert pool is not None

        async def run_one() -> int:
            async with pool.acquire() as adapter:
                executor = QueryExecutor(adapter, app.state.bus)
                run = await executor.run("SELECT 1 AS a")
                emitted = 0
                async for batch in run.rows:
                    emitted += len(batch.rows)
                return emitted

        results = await asyncio.gather(run_one(), run_one())
        assert list(results) == [1, 1]
