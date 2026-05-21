"""Typed asynchronous event bus.

The bus is the spine of Teridex's internal architecture. Publishers fire and
forget; subscribers receive events on their own coroutine. Events are Pydantic
models — type the subscriber by the concrete class.

Design notes:
* Subscribers are coroutines (``async def``); slow subscribers cannot block
  publishers.
* Each subscriber gets its own ``asyncio.Queue`` so a slow consumer cannot
  back-pressure others. Queue overflow drops the *oldest* event and logs.
* Sync-context publish via :meth:`EventBus.publish` is non-blocking.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from teridex_core.logging import get_logger

logger = get_logger(__name__)


class Event(BaseModel):
    """Base event."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


E = TypeVar("E", bound=Event)
Handler = Callable[[Any], Awaitable[None]]


class ConnectionOpened(Event):
    connection_id: str
    dsn_scheme: str


class ConnectionClosed(Event):
    connection_id: str


class QueryStarted(Event):
    query_id: str
    connection_id: str
    sql_preview: str


class QueryProgress(Event):
    query_id: str
    rows_emitted: int


class QueryCompleted(Event):
    query_id: str
    rows: int
    duration_ms: float


class QueryFailed(Event):
    query_id: str
    error_code: str
    message: str


class QueryCancelled(Event):
    query_id: str


class SchemaRefreshed(Event):
    connection_id: str


class PluginLoaded(Event):
    plugin_id: str


class PluginUnloaded(Event):
    plugin_id: str


class _Subscription:
    __slots__ = ("event_type", "handler", "queue", "task")

    def __init__(self, event_type: type[Event], handler: Handler, queue_size: int) -> None:
        self.event_type = event_type
        self.handler = handler
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self.task: asyncio.Task[None] | None = None


class EventBus:
    """In-process async pub/sub."""

    def __init__(self, *, queue_size: int = 1024) -> None:
        self._queue_size = queue_size
        self._subs: list[_Subscription] = []
        self._closed = False

    def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None:
        if self._closed:
            raise RuntimeError("EventBus is closed")
        sub = _Subscription(event_type, handler, self._queue_size)
        sub.task = asyncio.create_task(self._drain(sub), name=f"eventbus:{event_type.__name__}")
        self._subs.append(sub)

    async def _drain(self, sub: _Subscription) -> None:
        while True:
            event = await sub.queue.get()
            try:
                await sub.handler(event)
            except Exception:
                logger.exception(
                    "event_handler_failed",
                    event_type=type(event).__name__,
                    handler=getattr(sub.handler, "__qualname__", repr(sub.handler)),
                )

    def publish(self, event: Event) -> None:
        """Non-blocking publish. Safe to call from sync code or async code."""
        if self._closed:
            return
        for sub in self._subs:
            if not isinstance(event, sub.event_type):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
                logger.warning(
                    "event_queue_full",
                    event_type=type(event).__name__,
                    handler=getattr(sub.handler, "__qualname__", repr(sub.handler)),
                )
                with _suppress(asyncio.QueueFull):
                    sub.queue.put_nowait(event)

    async def close(self) -> None:
        self._closed = True
        for sub in self._subs:
            if sub.task is not None:
                sub.task.cancel()
        for sub in self._subs:
            if sub.task is not None:
                with _suppress(asyncio.CancelledError):
                    await sub.task
        self._subs.clear()


class _suppress:  # noqa: N801 - tiny utility
    def __init__(self, *exc: type[BaseException]) -> None:
        self.exc = exc

    def __enter__(self) -> None:
        return None

    def __exit__(self, et: type[BaseException] | None, *_: Any) -> bool:
        return et is not None and issubclass(et, self.exc)
