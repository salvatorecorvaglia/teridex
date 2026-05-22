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


# Lifecycle-terminal events: losing one of these strands UI state (a query
# stuck "running"), so they are never chosen as the victim when a queue
# overflows — see :meth:`EventBus.publish`.
_TERMINAL_EVENTS: tuple[type[Event], ...] = (QueryCompleted, QueryFailed, QueryCancelled)


class _Subscription:
    __slots__ = ("event_type", "handler", "queue", "task")

    def __init__(self, event_type: type[Event], handler: Handler, queue_size: int) -> None:
        self.event_type = event_type
        self.handler = handler
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self.task: asyncio.Task[None] | None = None


class EventBus:
    """In-process async pub/sub.

    Each subscriber gets its own bounded ``asyncio.Queue``. When a subscriber
    is slow and its queue fills, the *oldest* pending event is dropped to make
    room for the new one — the bus prioritizes keeping publishers non-blocking
    over delivery guarantees. Drops are counted in :attr:`dropped_events` and
    logged at WARNING.
    """

    def __init__(self, *, queue_size: int = 1024) -> None:
        self._queue_size = queue_size
        self._subs: list[_Subscription] = []
        self._closed = False
        self.dropped_events = 0

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], Awaitable[None]],
        *,
        queue_size: int | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("EventBus is closed")
        sub = _Subscription(event_type, handler, queue_size or self._queue_size)
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
                self._handle_overflow(sub, event)

    def _handle_overflow(self, sub: _Subscription, event: Event) -> None:
        """Make room in a full queue, preserving lifecycle-terminal events.

        If the incoming event is terminal, we must ensure it is delivered.
        We scan the queue for a non-terminal event to evict (from oldest to newest).
        If we find one, we remove it to make room.
        If all events in the queue are terminal, and the incoming event is also
        terminal, we append it directly (growing the queue).
        Otherwise, if the incoming event is not terminal and we can't evict
        anything (e.g., queue has only terminal events), the incoming event is dropped.
        """
        # Find a non-terminal event to evict (scanning oldest to newest)
        evict_idx = -1
        # sub.queue._queue is the internal deque.
        for i, q_ev in enumerate(sub.queue._queue):  # type: ignore[attr-defined]
            if not isinstance(q_ev, _TERMINAL_EVENTS):
                evict_idx = i
                break

        if evict_idx != -1:
            # We found a non-terminal event to evict. Remove it from the deque.
            evicted = sub.queue._queue[evict_idx]  # type: ignore[attr-defined]
            del sub.queue._queue[evict_idx]  # type: ignore[attr-defined]
            self.dropped_events += 1
            # Put the incoming event. It will succeed because qsize < maxsize.
            sub.queue.put_nowait(event)
            dropped = type(evicted).__name__
        # All events currently in the queue are terminal events.
        elif isinstance(event, _TERMINAL_EVENTS):
            # Growing the queue is allowed for terminal events to prevent losing them.
            sub.queue._queue.append(event)  # type: ignore[attr-defined]
            dropped = None
        else:
            # Incoming event is non-terminal, we drop it.
            self.dropped_events += 1
            dropped = type(event).__name__

        if dropped is not None:
            logger.warning(
                "event_queue_full",
                event_type=type(event).__name__,
                dropped_event=dropped,
                handler=getattr(sub.handler, "__qualname__", repr(sub.handler)),
                dropped_total=self.dropped_events,
            )

    async def close(self) -> None:
        self._closed = True
        for sub in self._subs:
            if sub.task is not None:
                sub.task.cancel()
        for sub in self._subs:
            if sub.task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await sub.task
        self._subs.clear()
