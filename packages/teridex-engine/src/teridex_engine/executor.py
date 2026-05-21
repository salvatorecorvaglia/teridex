"""High-level query executor.

Wraps a :class:`DatabaseAdapter`, emits lifecycle events on an
:class:`EventBus`, owns per-run cancellation, and surfaces a clean
:class:`QueryRun` handle to the UI.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from teridex_core.errors import QueryCancelledError, QueryError
from teridex_core.events import (
    EventBus,
    QueryCancelled,
    QueryCompleted,
    QueryFailed,
    QueryProgress,
    QueryStarted,
)
from teridex_core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from teridex_core.models.query import QueryHandle, QueryStatus
    from teridex_core.models.result import ResultBatch
    from teridex_core.protocols.adapter import DatabaseAdapter

logger = get_logger(__name__)


@dataclass
class QueryRun:
    """Handle to an executing query."""

    handle: QueryHandle
    rows: AsyncIterator[ResultBatch]
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    rows_emitted: int = 0

    @property
    def query_id(self) -> str:
        return self.handle.query_id

    @property
    def status(self) -> QueryStatus:
        return self.handle.status

    @property
    def duration_ms(self) -> float | None:
        return self.handle.duration_ms


class QueryExecutor:
    """Executes SQL against an adapter and broadcasts lifecycle events."""

    def __init__(self, adapter: DatabaseAdapter, event_bus: EventBus) -> None:
        self._adapter = adapter
        self._bus = event_bus

    async def run(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        *,
        batch_size: int = 1000,
        progress_every: int = 5000,
    ) -> QueryRun:
        """Start execution and return a :class:`QueryRun` whose ``rows`` you iterate.

        The returned iterator emits events as it consumes the stream.
        """
        started = time.perf_counter()
        try:
            handle = await self._adapter.execute(sql, params)
        except QueryError as exc:
            self._bus.publish(
                QueryFailed(
                    query_id="-",
                    error_code=getattr(exc, "code", "teridex.query"),
                    message=str(exc),
                )
            )
            raise

        self._bus.publish(
            QueryStarted(
                query_id=handle.query_id,
                connection_id=handle.connection_id,
                sql_preview=sql[:120],
            )
        )

        # Capture the source iterator locally so the closure cannot recursively
        # iterate ``run.rows`` after we reassign it to the wrapper below.
        source = await self._adapter.stream(handle, batch_size=batch_size)
        run = QueryRun(handle=handle, rows=source)

        async def _wrap() -> AsyncIterator[ResultBatch]:
            try:
                async for batch in source:
                    run.rows_emitted += len(batch.rows)
                    if (
                        run.rows_emitted > 0
                        and progress_every > 0
                        and run.rows_emitted % progress_every < batch_size
                    ):
                        self._bus.publish(
                            QueryProgress(query_id=handle.query_id, rows_emitted=run.rows_emitted)
                        )
                    yield batch
                self._bus.publish(
                    QueryCompleted(
                        query_id=handle.query_id,
                        rows=run.rows_emitted,
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                    )
                )
            except QueryCancelledError:
                self._bus.publish(QueryCancelled(query_id=handle.query_id))
                raise
            except QueryError as exc:
                self._bus.publish(
                    QueryFailed(
                        query_id=handle.query_id,
                        error_code=getattr(exc, "code", "teridex.query"),
                        message=str(exc),
                    )
                )
                raise

        run.rows = _wrap()
        return run

    async def cancel(self, run: QueryRun) -> None:
        """Cooperative cancellation; safe to call multiple times."""
        run.cancel_event.set()
        await self._adapter.cancel(run.handle)
        logger.info("query_cancel_requested", query_id=run.handle.query_id)
