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

            async def try_acquire() -> None:
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


@pytest.mark.asyncio
async def test_pool_close_cancellation_safety_does_not_leak_adapter() -> None:
    """Closing the pool cancels connection tasks but lets cleanup finish to avoid leaks."""
    connections_created = []

    async def tracking_factory(dsn: Dsn) -> DatabaseAdapter:
        a = SQLiteAdapter()
        await a.connect(dsn)
        connections_created.append(a)
        # Yield to allow outer acquire to yield before returning
        await asyncio.sleep(0.01)
        return a

    pool = ConnectionPool(Dsn.parse(_MEM), tracking_factory, size=1)

    async def try_acquire() -> None:
        async with pool.acquire():
            await asyncio.sleep(0.1)

    task = asyncio.create_task(try_acquire())
    # Wait for connection to be created
    await asyncio.sleep(0.03)

    # Cancel the acquire task. Since connection is completed but try_acquire is sleeping,
    # this cancels try_acquire and triggers the cleanup/release task.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Close the pool.
    await pool.close()

    await asyncio.sleep(0.05)

    assert len(connections_created) > 0
    for a in connections_created:
        assert a.connected is False


@pytest.mark.asyncio
async def test_close_closes_an_adapter_that_was_checked_out() -> None:
    """Closing the pool must not leak the connections that were in use.

    ``close()`` empties ``_all``, so the release path could no longer find the
    checked-out adapter in it and skipped closing that connection entirely.
    """
    pool = ConnectionPool(Dsn.parse(_MEM), _factory, size=2)
    released: list[DatabaseAdapter] = []

    async def _hold() -> None:
        async with pool.acquire() as adapter:
            released.append(adapter)
            await asyncio.sleep(0.05)

    holder = asyncio.create_task(_hold())
    for _ in range(50):
        await asyncio.sleep(0.01)
        if released:
            break
    assert released, "never acquired an adapter"

    await pool.close()
    await holder
    for _ in range(50):
        await asyncio.sleep(0.01)
        if not released[0].connected:  # type: ignore[attr-defined]
            break
    assert not released[0].connected, "checked-out adapter was left open"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_preload_adopts_an_existing_connection() -> None:
    pool = ConnectionPool(Dsn.parse(_MEM), _factory, size=1)
    seeded = await _factory(Dsn.parse(_MEM))
    await pool.preload(seeded)
    try:
        async with pool.acquire() as adapter:
            assert adapter is seeded
        # Still usable after being returned.
        async with pool.acquire() as adapter:
            assert adapter is seeded
    finally:
        await pool.close()
    assert not seeded.connected  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_preload_refuses_to_exceed_capacity() -> None:
    pool = ConnectionPool(Dsn.parse(_MEM), _factory, size=1)
    await pool.preload(await _factory(Dsn.parse(_MEM)))
    try:
        with pytest.raises(ValueError, match="capacity"):
            await pool.preload(await _factory(Dsn.parse(_MEM)))
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_release_rolls_back_a_transaction_left_open() -> None:
    """A connection must never return to the pool inside a transaction."""
    pool = ConnectionPool(Dsn.parse(_MEM), _factory, size=1)
    try:
        async with pool.acquire() as adapter:
            await adapter.execute("BEGIN")
            assert adapter._conn.in_transaction  # type: ignore[attr-defined]
            leaked = adapter
        assert not leaked._conn.in_transaction, (  # type: ignore[attr-defined]
            "adapter went back to the pool still in a transaction"
        )
    finally:
        await pool.close()
