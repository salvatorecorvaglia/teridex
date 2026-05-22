"""Bounded asyncio connection pool.

Adapters are cheap to construct but expensive to connect. The pool reuses
connected adapter instances across queries and bounds the concurrency.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from teridex_core.logging import get_logger
from teridex_core.models.connection import Dsn
from teridex_core.protocols.adapter import DatabaseAdapter

logger = get_logger(__name__)

AdapterFactory = Callable[[Dsn], Awaitable[DatabaseAdapter]]


class ConnectionPool:
    """Bounded pool of pre-connected adapter instances for a single DSN."""

    def __init__(self, dsn: Dsn, factory: AdapterFactory, *, size: int = 5) -> None:
        if size < 1:
            raise ValueError("pool size must be >= 1")
        self._dsn = dsn
        self._factory = factory
        self._size = size
        self._idle: asyncio.LifoQueue[DatabaseAdapter] = asyncio.LifoQueue(maxsize=size)
        self._sem = asyncio.Semaphore(size)
        self._all: list[DatabaseAdapter] = []
        self._closed = False
        self._lock = asyncio.Lock()
        self._waiters: set[asyncio.Future[DatabaseAdapter]] = set()

    async def _acquire(self) -> DatabaseAdapter:
        if self._closed:
            raise RuntimeError("pool is closed")
        await self._sem.acquire()
        try:
            return self._idle.get_nowait()
        except asyncio.QueueEmpty:
            pass
        async with self._lock:
            if len(self._all) < self._size:
                adapter = await self._factory(self._dsn)
                self._all.append(adapter)
                return adapter
        # Someone else created one — wait for an idle one. Track the waiter
        # so ``close()`` can wake it instead of leaving it hung forever.
        getter: asyncio.Future[DatabaseAdapter] = asyncio.ensure_future(self._idle.get())
        self._waiters.add(getter)
        try:
            return await getter
        finally:
            self._waiters.discard(getter)

    async def _release(self, adapter: DatabaseAdapter) -> None:
        if self._closed:
            await adapter.close()
            self._sem.release()
            return
        await self._idle.put(adapter)
        self._sem.release()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[DatabaseAdapter]:
        adapter = await self._acquire()
        try:
            yield adapter
        finally:
            await self._release(adapter)

    async def close(self) -> None:
        self._closed = True
        for getter in self._waiters:
            getter.cancel()
        self._waiters.clear()
        for adapter in self._all:
            try:
                await adapter.close()
            except Exception:
                logger.exception("pool_close_adapter_failed")
        self._all.clear()
