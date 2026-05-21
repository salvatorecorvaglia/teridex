"""Database adapter protocol — the seam every database plugs into."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from teridex_core.models.connection import Dsn
    from teridex_core.models.query import QueryHandle, QueryMetadata
    from teridex_core.models.result import ResultBatch
    from teridex_core.models.schema import SchemaSnapshot


@runtime_checkable
class Transaction(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def __aenter__(self) -> Transaction: ...
    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...


@runtime_checkable
class DatabaseAdapter(Protocol):
    """Protocol for an async database adapter.

    Implementations live in ``teridex_adapters`` and are looked up by URL
    scheme via the adapter registry.
    """

    name: ClassVar[str]
    schemes: ClassVar[tuple[str, ...]]

    async def connect(self, dsn: Dsn) -> None: ...
    async def close(self) -> None: ...
    async def ping(self) -> bool: ...

    async def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryHandle: ...
    async def stream(
        self, handle: QueryHandle, *, batch_size: int = 1000
    ) -> AsyncIterator[ResultBatch]: ...
    async def metadata(self, handle: QueryHandle) -> QueryMetadata: ...
    async def cancel(self, handle: QueryHandle) -> None: ...

    async def begin(self) -> Transaction: ...

    async def introspect(self) -> SchemaSnapshot: ...
