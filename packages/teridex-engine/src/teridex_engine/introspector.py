"""Schema introspection wrapper with caching + event emission."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teridex_core.events import EventBus, SchemaRefreshed
from teridex_core.logging import get_logger

if TYPE_CHECKING:
    from teridex_core.models.schema import (
        ForeignKey,
        Index,
        SchemaSnapshot,
        TableColumn,
    )
    from teridex_core.protocols.adapter import DatabaseAdapter

logger = get_logger(__name__)


class Introspector:
    """Wraps adapter introspection with an in-memory cache.

    Cache invalidates on explicit :meth:`refresh` or :meth:`invalidate`.
    """

    def __init__(self, adapter: DatabaseAdapter, bus: EventBus) -> None:
        self._adapter = adapter
        self._bus = bus
        self._cache: SchemaSnapshot | None = None

    async def snapshot(self, *, force: bool = False, lazy: bool = False) -> SchemaSnapshot:
        if self._cache is None or force:
            self._cache = await self._adapter.introspect(lazy=lazy)
            self._bus.publish(SchemaRefreshed(connection_id=self._cache.connection_id))
            logger.debug(
                "schema_refreshed",
                connection_id=self._cache.connection_id,
                objects=self._cache.object_count,
            )
        return self._cache

    async def refresh(self, *, lazy: bool = False) -> SchemaSnapshot:
        return await self.snapshot(force=True, lazy=lazy)

    def invalidate(self) -> None:
        self._cache = None

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        return await self._adapter.fetch_columns(schema, name)

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        return await self._adapter.fetch_foreign_keys(schema, name)

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        return await self._adapter.fetch_indexes(schema, name)
