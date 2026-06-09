"""DuckDB adapter.

DuckDB's Python driver is sync; we wrap it with ``asyncio.to_thread`` and a
per-connection lock so the embedded DB is touched by one thread at a time.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

import duckdb

from teridex_adapters._introspect import SchemaIntrospector
from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import AbstractAdapter, connection_id
from teridex_core.errors import AdapterError, QueryCancelledError, QueryError
from teridex_core.logging import get_logger
from teridex_core.models.connection import Dsn
from teridex_core.models.query import QueryHandle, QueryMetadata, QueryStatus
from teridex_core.models.result import Column, ResultBatch
from teridex_core.models.schema import (
    ForeignKey,
    Index,
    SchemaSnapshot,
    TableColumn,
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
        except duckdb.Error:
            return False

    async def _exec_sync(self, sql: str, params: Mapping[str, Any] | None = None) -> Any:
        if self._conn is None:
            raise AdapterError("duckdb: not connected")
        conn = self._conn
        async with self._lock:

            def _run() -> Any:
                if params:
                    # Pass the mapping through unchanged so DuckDB binds by name
                    # ($name placeholders). Flattening to .values() would bind
                    # positionally and silently mismatch named parameters.
                    return conn.execute(sql, dict(params))
                return conn.execute(sql)

            return await asyncio.to_thread(_run)

    async def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryHandle:
        if self._conn is None:
            raise AdapterError("duckdb: not connected")
        handle = QueryHandle(
            connection_id=connection_id(self._conn),
            sql=sql,
            params=dict(params) if params else None,
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
            async with self._lock:
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
            try:
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
                    try:
                        async with self._lock:
                            rows = await asyncio.to_thread(conn.fetchmany, batch_size)
                    except duckdb.Error as exc:
                        if cancel.is_set():
                            handle.mark_done(QueryStatus.CANCELLED)
                            raise QueryCancelledError(
                                "query cancelled", context={"query_id": handle.query_id}
                            ) from exc
                        raise QueryError(str(exc), context={"sql": handle.sql}) from exc
                    if not rows:
                        handle.mark_done(QueryStatus.SUCCEEDED)
                        yield ResultBatch(columns=columns, rows=[], is_last=True)
                        return
                    yield ResultBatch(columns=columns, rows=[tuple(r) for r in rows], is_last=False)
            finally:
                self._forget(handle)

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
            logger.warning("duckdb_interrupt_failed", query_id=handle.query_id, error=str(exc))

    async def begin(self) -> Transaction:
        return _DuckDBTransaction(self)

    async def introspect(self, *, lazy: bool = False) -> SchemaSnapshot:
        if self._conn is None:
            raise AdapterError("duckdb: not connected")
        introspector = _DuckDBIntrospector(self._conn, self._dsn, self._lock)
        return await introspector.build(lazy=lazy)

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        if self._conn is None:
            raise AdapterError("duckdb: not connected")
        introspector = _DuckDBIntrospector(self._conn, self._dsn, self._lock)
        return await introspector.fetch_columns(schema, name)

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        return []

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        return []


class _DuckDBIntrospector(SchemaIntrospector):
    """DuckDB-specific schema introspector.

    All synchronous DuckDB calls run via ``asyncio.to_thread`` under the
    adapter's connection lock to maintain DuckDB's single-threaded safety.
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        dsn: Dsn | None,
        lock: asyncio.Lock,
    ) -> None:
        self._conn = conn
        self._dsn = dsn
        self._lock = lock

    def connection_id(self) -> str:
        return connection_id(self._conn)

    def database_name(self) -> str | None:
        return self._dsn.database if self._dsn else None

    async def list_objects(self) -> list[tuple[str, str, str]]:
        conn = self._conn

        def _list() -> list[tuple[str, str, str]]:
            rows = conn.execute(
                "SELECT table_schema, table_name, table_type "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema')"
            ).fetchall()
            result: list[tuple[str, str, str]] = []
            for schema_name, table_name, kind_raw in rows:
                kind = "view" if kind_raw == "VIEW" else "table"
                result.append((schema_name, table_name, kind))
            return result

        async with self._lock:
            return await asyncio.to_thread(_list)

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        conn = self._conn

        def _fetch() -> list[TableColumn]:
            cols = conn.execute(
                "SELECT column_name, data_type, is_nullable, column_default, ordinal_position "
                "FROM information_schema.columns "
                "WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",
                [schema, name],
            ).fetchall()
            return [
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

        async with self._lock:
            return await asyncio.to_thread(_fetch)
