from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.models.connection import Dsn
from teridex_engine.pool import ConnectionPool

if TYPE_CHECKING:
    from teridex_core.protocols.adapter import DatabaseAdapter

_MEM = "sqlite:///:memory:"


async def _factory(dsn: Dsn) -> DatabaseAdapter:
    a = SQLiteAdapter()
    await a.connect(dsn)
    return a


@pytest.mark.asyncio
async def test_pool_reuses_connection() -> None:
    pool = ConnectionPool(Dsn.parse(_MEM), _factory, size=2)
    try:
        async with pool.acquire() as a1:
            assert await a1.ping()
        async with pool.acquire() as a2:
            assert await a2.ping()
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_factory_failure_does_not_leak_semaphore_slot() -> None:
    """A failed adapter factory must release the slot it tentatively held.

    Before the fix, ``size`` consecutive factory failures permanently drained
    the semaphore and every later ``acquire()`` hung forever.
    """
    calls = {"n": 0}

    async def flaky(dsn: Dsn) -> DatabaseAdapter:
        calls["n"] += 1
        if calls["n"] <= 3:
            raise RuntimeError("connect failed")
        return await _factory(dsn)

    pool = ConnectionPool(Dsn.parse(_MEM), flaky, size=1)
    try:
        for _ in range(3):
            with pytest.raises(RuntimeError, match="connect failed"):
                async with pool.acquire():
                    pass
        # Would hang forever if the slot had leaked.
        async with asyncio.timeout(2):
            async with pool.acquire() as adapter:
                assert await adapter.ping()
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_acquire_after_close_raises() -> None:
    pool = ConnectionPool(Dsn.parse(_MEM), _factory, size=1)
    await pool.close()
    with pytest.raises(RuntimeError, match="closed"):
        async with pool.acquire():
            pass


@pytest.mark.asyncio
async def test_pool_acquire_cancellation_safety() -> None:
    """Acquisition and release must not leak slots or adapters under cancellation."""
    pool = ConnectionPool(Dsn.parse(_MEM), _factory, size=1)
    try:
        async with pool.acquire() as a1:
            assert await a1.ping()

            async def try_acquire():
                async with pool.acquire():
                    pass

            task = asyncio.create_task(try_acquire())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        async with asyncio.timeout(1):
            async with pool.acquire() as a2:
                assert await a2.ping()
    finally:
        await pool.close()
