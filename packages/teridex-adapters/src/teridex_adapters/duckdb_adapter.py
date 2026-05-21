"""DuckDB adapter.

DuckDB's Python driver is sync; we wrap it with ``asyncio.to_thread`` and a
per-connection lock so the embedded DB is touched by one thread at a time.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

import duckdb

from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import AbstractAdapter
from teridex_core.errors import AdapterError, QueryCancelledError, QueryError
from teridex_core.logging import get_logger
from teridex_core.models.query import QueryHandle, QueryMetadata, QueryStatus
from teridex_core.models.result import Column, ResultBatch
from teridex_core.models.schema import (
    ForeignKey,
    Index,
    SchemaObject,
    SchemaSnapshot,
    Table,
    TableColumn,
    View,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from teridex_core.models.connection import Dsn
    from teridex_core.protocols.adapter import Transaction

logger = get_logger(__name__)


class _DuckDBTransaction:
    def __init__(self, adapter: DuckDBAdapter) -> None:
        self._adapter = adapter

    async def __aenter__(self) -> _DuckDBTransaction:
        await self._adapter._exec_sync("BEGIN")
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    async def commit(self) -> None:
        await self._adapter._exec_sync("COMMIT")

    async def rollback(self) -> None:
        await self._adapter._exec_sync("ROLLBACK")


class DuckDBAdapter(AbstractAdapter):
    name: ClassVar[str] = "duckdb"
    schemes: ClassVar[tuple[str, ...]] = ("duckdb",)

    def __init__(self) -> None:
        super().__init__()
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = asyncio.Lock()

    async def _do_connect(self, dsn: Dsn) -> None:
        path = dsn.database or ":memory:"
        # duckdb.connect is sync; wrap.
        self._conn = await asyncio.to_thread(duckdb.connect, path, read_only=False)

    async def _do_close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def ping(self) -> bool:
        if self._conn is None:
            return False
        try:
            await self._exec_sync("SELECT 1")
            return True
        except Exception:
            return False

    async def _exec_sync(self, sql: str, params: Mapping[str, Any] | None = None) -> Any:
        if self._conn is None:
            raise AdapterError("duckdb: not connected")
        conn = self._conn
        async with self._lock:

            def _run() -> Any:
                if params:
                    return conn.execute(sql, list(params.values()))
                return conn.execute(sql)

            return await asyncio.to_thread(_run)

    async def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryHandle:
        cid = id(self._conn)
        handle = QueryHandle(
            connection_id=hex(cid), sql=sql, params=dict(params) if params else None
        )
        handle.mark_running()
        try:
            await self._exec_sync(sql, params)
        except duckdb.Error as exc:
            handle.mark_done(QueryStatus.FAILED)
            raise QueryError(str(exc), context={"sql": sql}) from exc
        handle.mark_streaming()
        return handle

    async def stream(
        self, handle: QueryHandle, *, batch_size: int = 1000
    ) -> AsyncIterator[ResultBatch]:
        if self._conn is None:
            raise AdapterError("duckdb: not connected")
        cancel = self._cancel_event(handle)
        conn = self._conn

        async def _gen() -> AsyncIterator[ResultBatch]:
            description = await asyncio.to_thread(lambda: conn.description)
            columns = (
                [
                    Column(
                        name=d[0],
                        type=infer_column_type(str(d[1])),
                        type_native=str(d[1]),
                    )
                    for d in description
                ]
                if description
                else []
            )
            self._set_metadata(
                handle,
                QueryMetadata(
                    column_names=[c.name for c in columns],
                    column_types=[c.type_native or "" for c in columns],
                ),
            )
            if not columns:
                handle.mark_done(QueryStatus.SUCCEEDED)
                yield ResultBatch(columns=[], rows=[], is_last=True)
                return
            while True:
                if cancel.is_set():
                    handle.mark_done(QueryStatus.CANCELLED)
                    raise QueryCancelledError(
                        "query cancelled", context={"query_id": handle.query_id}
                    )
                rows = await asyncio.to_thread(conn.fetchmany, batch_size)
                if not rows:
                    handle.mark_done(QueryStatus.SUCCEEDED)
                    yield ResultBatch(columns=columns, rows=[], is_last=True)
                    return
                yield ResultBatch(columns=columns, rows=[tuple(r) for r in rows], is_last=False)

        return _gen()

    async def cancel(self, handle: QueryHandle) -> None:
        await super().cancel(handle)
        if self._conn is None:
            return
        # interrupt() is thread-safe and aborts the in-progress query on the
        # other thread; we MUST NOT hold ``_lock`` here or we'd deadlock the
        # worker thread we're trying to interrupt.
        conn = self._conn
        try:
            await asyncio.to_thread(conn.interrupt)
        except Exception as exc:
            logger.warning(
                "duckdb_interrupt_failed", query_id=handle.query_id, error=str(exc)
            )

    async def begin(self) -> Transaction:
        return _DuckDBTransaction(self)

    async def introspect(self) -> SchemaSnapshot:
        if self._conn is None:
            raise AdapterError("duckdb: not connected")
        conn = self._conn

        def _introspect() -> SchemaSnapshot:
            schemas: dict[str, list[SchemaObject]] = {}
            tables = conn.execute(
                "SELECT table_schema, table_name, table_type "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema')"
            ).fetchall()
            for schema_name, table_name, kind in tables:
                cols = conn.execute(
                    "SELECT column_name, data_type, is_nullable, column_default, ordinal_position "
                    "FROM information_schema.columns "
                    "WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",
                    [schema_name, table_name],
                ).fetchall()
                columns = [
                    TableColumn(
                        name=c[0],
                        type_native=c[1],
                        type=infer_column_type(c[1]),
                        nullable=c[2] == "YES",
                        default=c[3],
                        ordinal=c[4] or 0,
                    )
                    for c in cols
                ]
                obj: SchemaObject
                if kind == "VIEW":
                    obj = View(name=table_name, schema_name=schema_name, columns=columns)
                else:
                    obj = Table(name=table_name, schema_name=schema_name, columns=columns)
                schemas.setdefault(schema_name, []).append(obj)
            _ = ForeignKey, Index  # reserved for future native catalog queries
            return SchemaSnapshot(
                connection_id=hex(id(conn)),
                database=self._dsn.database if self._dsn else None,
                schemas=schemas,
            )

        return await asyncio.to_thread(_introspect)
