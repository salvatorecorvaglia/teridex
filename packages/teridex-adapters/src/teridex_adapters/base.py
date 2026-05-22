"""Abstract base class shared by all adapters.

Provides:
* DSN holding + lifecycle bookkeeping
* Cancellation flag plumbing (per-handle)
* Default introspection (subclasses can override with native catalog queries)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from teridex_core.errors import AdapterError
from teridex_core.logging import get_logger
from teridex_core.models.query import QueryHandle, QueryMetadata, QueryStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from teridex_core.models.connection import Dsn
    from teridex_core.models.result import ResultBatch
    from teridex_core.models.schema import (
        ForeignKey,
        Index,
        SchemaSnapshot,
        TableColumn,
    )
    from teridex_core.protocols.adapter import Transaction

logger = get_logger(__name__)


def connection_id(conn: object) -> str:
    """Stable per-process identifier for a driver connection object.

    Used for ``QueryHandle.connection_id`` / ``SchemaSnapshot.connection_id``.
    The value only needs to be stable for the connection's lifetime and
    distinct between live connections — ``id()`` satisfies both.
    """
    return hex(id(conn))


class AbstractAdapter(ABC):
    """Skeleton implementation of :class:`DatabaseAdapter`.

    Threading/concurrency contract: an adapter instance is **single-owner** —
    it serves one query at a time. The engine enforces this by handing every
    run a dedicated adapter from :class:`~teridex_engine.pool.ConnectionPool`.
    The per-handle ``_cancel_flags`` / ``_metadata`` dicts are therefore only
    mutated from one logical caller; they are not guarded for concurrent
    ``execute`` calls on the same instance.
    """

    name: ClassVar[str] = "abstract"
    schemes: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self._dsn: Dsn | None = None
        self._connected = False
        self._cancel_flags: dict[str, asyncio.Event] = {}
        self._metadata: dict[str, QueryMetadata] = {}

    # ---- lifecycle ----------------------------------------------------

    @property
    def dsn(self) -> Dsn:
        if self._dsn is None:
            raise AdapterError(
                f"{self.name}: not connected",
                context={"adapter": self.name},
            )
        return self._dsn

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, dsn: Dsn) -> None:
        self._dsn = dsn
        await self._do_connect(dsn)
        self._connected = True
        logger.info("adapter_connected", adapter=self.name, scheme=dsn.scheme)

    async def close(self) -> None:
        if not self._connected:
            return
        try:
            await self._do_close()
        finally:
            self._connected = False
            self._cancel_flags.clear()
            self._metadata.clear()
            logger.info("adapter_closed", adapter=self.name)

    @abstractmethod
    async def _do_connect(self, dsn: Dsn) -> None: ...

    @abstractmethod
    async def _do_close(self) -> None: ...

    @abstractmethod
    async def ping(self) -> bool: ...

    # ---- execution ----------------------------------------------------

    @abstractmethod
    async def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryHandle: ...

    @abstractmethod
    async def stream(
        self, handle: QueryHandle, *, batch_size: int = 1000
    ) -> AsyncIterator[ResultBatch]: ...

    async def metadata(self, handle: QueryHandle) -> QueryMetadata:
        return self._metadata.get(handle.query_id, QueryMetadata())

    async def cancel(self, handle: QueryHandle) -> None:
        # Create-or-get — cancel() must be effective even if stream() hasn't
        # been called yet for this handle (the executor may cancel between
        # execute and stream).
        self._cancel_event(handle).set()
        handle.mark_done(QueryStatus.CANCELLED)
        logger.info("adapter_cancel_requested", adapter=self.name, query_id=handle.query_id)

    def _cancel_event(self, handle: QueryHandle) -> asyncio.Event:
        flag = self._cancel_flags.get(handle.query_id)
        if flag is None:
            flag = asyncio.Event()
            self._cancel_flags[handle.query_id] = flag
        return flag

    def _set_metadata(self, handle: QueryHandle, meta: QueryMetadata) -> None:
        self._metadata[handle.query_id] = meta

    def _forget(self, handle: QueryHandle) -> None:
        self._cancel_flags.pop(handle.query_id, None)
        self._metadata.pop(handle.query_id, None)

    async def reset(self) -> None:
        self._cancel_flags.clear()
        self._metadata.clear()

    # ---- transactions / introspection --------------------------------

    @abstractmethod
    async def begin(self) -> Transaction: ...

    @abstractmethod
    async def introspect(self, *, lazy: bool = False) -> SchemaSnapshot: ...

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        return []

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        return []

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        return []
