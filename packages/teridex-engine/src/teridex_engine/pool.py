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
        self._tasks: set[asyncio.Task[None]] = set()

    async def _acquire(self) -> DatabaseAdapter:
        if self._closed:
            raise RuntimeError("pool is closed")
        await self._sem.acquire()
        # From here on, any failure/cancellation path must release the semaphore
        # (or delegate its release to _release if we got an adapter).
        adapter_to_release: DatabaseAdapter | None = None
        try:
            try:
                return self._idle.get_nowait()
            except asyncio.QueueEmpty:
                pass
            # Decide under the lock so ``close()`` cannot race the waiter set:
            # either build a new adapter or register a tracked waiter.
            async with self._lock:
                if self._closed:
                    raise RuntimeError("pool is closed")
                if len(self._all) < self._size:
                    # Shield creation so we don't leak an untracked connection on cancellation
                    async def _make() -> DatabaseAdapter:
                        a = await self._factory(self._dsn)
                        self._all.append(a)
                        return a

                    adapter = await asyncio.shield(_make())
                    adapter_to_release = adapter
                    return adapter
                # Someone else created one — wait for an idle adapter. Track
                # the waiter so ``close()`` can wake it instead of hanging it.
                getter: asyncio.Future[DatabaseAdapter] = asyncio.ensure_future(self._idle.get())
                self._waiters.add(getter)
            try:
                adapter = await getter
                adapter_to_release = adapter
                return adapter
            except asyncio.CancelledError:
                if not getter.done():
                    getter.cancel()
                elif not getter.cancelled() and getter.exception() is None:
                    adapter_to_release = getter.result()
                raise
            finally:
                self._waiters.discard(getter)
        except BaseException:
            if adapter_to_release is not None:
                task = asyncio.create_task(self._release(adapter_to_release))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            else:
                self._sem.release()
            raise

    async def _release(self, adapter: DatabaseAdapter) -> None:
        async def _do_release() -> None:
            try:
                await adapter.reset()
            except Exception:
                logger.exception("pool_release_reset_failed")
            finally:
                async with self._lock:
                    if self._closed:
                        if adapter in self._all:
                            self._all.remove(adapter)
                            await adapter.close()
                        self._sem.release()
                    else:
                        await self._idle.put(adapter)
                        self._sem.release()

        # Shield the cleanup so that even if the outer task gets cancelled,
        # the semaphore and adapter are safely returned/released.
        await asyncio.shield(_do_release())

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[DatabaseAdapter]:
        adapter = await self._acquire()
        try:
            yield adapter
        finally:
            await self._release(adapter)

    async def close(self) -> None:
        # Hold the lock so a concurrent ``_acquire`` either observes ``_closed``
        # before registering a waiter or is woken by the cancellation below.
        async with self._lock:
            self._closed = True
            for getter in self._waiters:
                getter.cancel()
            self._waiters.clear()
            adapters = list(self._all)
            self._all.clear()
        for adapter in adapters:
            try:
                await adapter.close()
            except Exception:
                logger.exception("pool_close_adapter_failed")
