"""PostgreSQL adapter using asyncpg directly (native async, server-side cursors)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, ClassVar, cast

import asyncpg

from teridex_adapters._introspect import SchemaIntrospector
from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import AbstractAdapter, connection_id
from teridex_core.errors import AdapterError, QueryCancelledError, QueryError
from teridex_core.logging import get_logger
from teridex_core.models.query import QueryHandle, QueryMetadata, QueryStatus
from teridex_core.models.result import Column, ResultBatch
from teridex_core.models.schema import (
    ForeignKey,
    Index,
    SchemaSnapshot,
    TableColumn,
    View,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from typing import Literal

    from teridex_core.models.connection import Dsn
    from teridex_core.protocols.adapter import Transaction

logger = get_logger(__name__)


class _PostgresTransaction:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self._tx: Any = None

    async def __aenter__(self) -> _PostgresTransaction:
        self._tx = self._conn.transaction()
        await self._tx.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    async def commit(self) -> None:
        if self._tx is not None:
            await self._tx.commit()
            self._tx = None

    async def rollback(self) -> None:
        if self._tx is not None:
            await self._tx.rollback()
            self._tx = None


class PostgresAdapter(AbstractAdapter):
    name: ClassVar[str] = "postgres"
    schemes: ClassVar[tuple[str, ...]] = ("postgres", "postgresql")

    def __init__(self) -> None:
        super().__init__()
        self._conn: asyncpg.Connection | None = None
        self._backend_pid: int | None = None
        self._active_query_id: str | None = None
        self._lock = asyncio.Lock()

    async def _do_connect(self, dsn: Dsn) -> None:
        self._conn = await asyncpg.connect(dsn.render(mask_password=False))
        self._backend_pid = await self._conn.fetchval("SELECT pg_backend_pid()")

    async def _do_close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._backend_pid = None
        self._active_query_id = None

    async def ping(self) -> bool:
        if self._conn is None:
            return False
        try:
            await self._conn.fetchval("SELECT 1")
            return True
        except asyncpg.PostgresError:
            return False

    async def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryHandle:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        handle = QueryHandle(
            connection_id=connection_id(self._conn),
            sql=sql,
            params=dict(params) if params else None,
        )
        handle.mark_running()
        self._active_query_id = handle.query_id
        # Actual execution is deferred to stream() so we can use a server-side
        # cursor for SELECTs and ``execute`` for DML. The SQL travels on the
        # handle itself — no per-adapter bookkeeping dict to leak.
        handle.mark_streaming()
        return handle

    async def stream(
        self, handle: QueryHandle, *, batch_size: int = 1000
    ) -> AsyncIterator[ResultBatch]:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        sql = handle.sql
        if not sql:
            raise AdapterError("postgres: stream() called with an empty handle")
        cancel = self._cancel_event(handle)
        conn = self._conn

        # Convert dict parameters to positional list for asyncpg.
        # Postgres uses $1, $2... placeholders, so keys must be stringified positive integers.
        # We construct a list where args[i] corresponds to $(i+1).
        args = []
        if handle.params:
            try:
                keys = [int(k) for k in handle.params]
                if any(k <= 0 for k in keys):
                    raise ValueError("Placeholder indices must be positive integers >= 1")
                max_key = max(keys) if keys else 0
                args = [None] * max_key
                for k, v in handle.params.items():
                    args[int(k) - 1] = v
            except ValueError as exc:
                raise QueryError(
                    "postgres: invalid parameters. Parameters must be a dictionary "
                    "with stringified integer keys corresponding to $1, $2, etc.",
                    context={"sql": sql, "params": handle.params},
                ) from exc

        async def _gen() -> AsyncIterator[ResultBatch]:
            try:
                try:
                    stmt = await conn.prepare(sql)
                except asyncpg.PostgresError as exc:
                    handle.mark_done(QueryStatus.FAILED)
                    raise QueryError(str(exc), context={"sql": sql}) from exc

                attrs = stmt.get_attributes()
                if not attrs:
                    # DML / DDL (no columns returned) — execute and finalize
                    try:
                        await stmt.fetch(*args)
                        status = stmt.get_statusmsg()
                    except asyncpg.PostgresError as exc:
                        if cancel.is_set():
                            handle.mark_done(QueryStatus.CANCELLED)
                            raise QueryCancelledError(
                                "query cancelled", context={"query_id": handle.query_id}
                            ) from exc
                        handle.mark_done(QueryStatus.FAILED)
                        raise QueryError(str(exc), context={"sql": sql}) from exc
                    handle.mark_done(QueryStatus.SUCCEEDED)
                    self._set_metadata(
                        handle,
                        QueryMetadata(server_message=status, column_names=[], column_types=[]),
                    )
                    yield ResultBatch(columns=[], rows=[], is_last=True)
                    return

                # DQL / RETURNING — stream using cursor
                columns = [
                    Column(
                        name=a.name,
                        type=infer_column_type(a.type.name),
                        type_native=a.type.name,
                    )
                    for a in attrs
                ]
                self._set_metadata(
                    handle,
                    QueryMetadata(
                        column_names=[c.name for c in columns],
                        column_types=[c.type_native or "" for c in columns],
                    ),
                )

                try:
                    async with conn.transaction():
                        cur = await stmt.cursor(*args)
                        while True:
                            if cancel.is_set():
                                handle.mark_done(QueryStatus.CANCELLED)
                                raise QueryCancelledError(
                                    "query cancelled", context={"query_id": handle.query_id}
                                )
                            records = await cur.fetch(batch_size)
                            if not records:
                                handle.mark_done(QueryStatus.SUCCEEDED)
                                yield ResultBatch(columns=columns, rows=[], is_last=True)
                                return
                            yield ResultBatch(
                                columns=columns,
                                rows=[tuple(r.values()) for r in records],
                                is_last=False,
                            )
                except asyncpg.PostgresError as exc:
                    if cancel.is_set():
                        handle.mark_done(QueryStatus.CANCELLED)
                        raise QueryCancelledError(
                            "query cancelled", context={"query_id": handle.query_id}
                        ) from exc
                    handle.mark_done(QueryStatus.FAILED)
                    raise QueryError(str(exc), context={"sql": sql}) from exc
            finally:
                self._forget(handle)

        return _gen()

    async def cancel(self, handle: QueryHandle) -> None:
        await super().cancel(handle)
        if self._active_query_id != handle.query_id:
            return
        # The live connection is busy running the user's query, so we can't
        # use it to issue pg_cancel_backend — open a short-lived side
        # connection instead and target the saved backend PID.
        if self._backend_pid is None or self._dsn is None:
            return
        dsn = self._dsn
        try:
            side = await asyncio.wait_for(
                asyncpg.connect(dsn.render(mask_password=False)),
                timeout=5.0,
            )
        except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
            logger.warning(
                "postgres_cancel_side_connect_failed",
                query_id=handle.query_id,
                error=str(exc),
            )
            return
        try:
            with contextlib.suppress(asyncpg.PostgresError):
                await side.execute("SELECT pg_cancel_backend($1)", self._backend_pid)
        finally:
            with contextlib.suppress(Exception):
                await side.close()

    def _forget(self, handle: QueryHandle) -> None:
        super()._forget(handle)
        if self._active_query_id == handle.query_id:
            self._active_query_id = None

    async def reset(self) -> None:
        await super().reset()
        self._active_query_id = None

    async def begin(self) -> Transaction:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        return _PostgresTransaction(self._conn)

    async def introspect(self, *, lazy: bool = False) -> SchemaSnapshot:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        async with self._lock:
            return await _PostgresIntrospector(self, self._conn).build(lazy=lazy)

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        async with self._lock:
            return await _PostgresIntrospector(self, self._conn).fetch_columns(schema, name)

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        async with self._lock:
            return await _PostgresIntrospector(self, self._conn).fetch_foreign_keys(schema, name)

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        async with self._lock:
            return await _PostgresIntrospector(self, self._conn).fetch_indexes(schema, name)


class _PostgresIntrospector(SchemaIntrospector):
    def __init__(self, adapter: PostgresAdapter, conn: asyncpg.Connection) -> None:
        self._adapter = adapter
        self._conn = conn

    def connection_id(self) -> str:
        return connection_id(self._conn)

    def database_name(self) -> str | None:
        return self._adapter._dsn.database if self._adapter._dsn else None

    async def list_objects(self) -> list[tuple[str, str, str]]:
        rows = await self._conn.fetch(
            """
            SELECT n.nspname AS schema_name, c.relname AS name,
                   CASE c.relkind WHEN 'v' THEN 'view'
                                  WHEN 'm' THEN 'materialized_view'
                                  ELSE 'table' END AS kind
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r','v','m','p')
              AND n.nspname NOT IN ('pg_catalog','information_schema')
            ORDER BY n.nspname, c.relname
            """
        )
        return [(r["schema_name"], r["name"], r["kind"]) for r in rows]

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        rows = await self._conn.fetch(
            """
            SELECT 
                c.column_name, 
                c.data_type, 
                c.is_nullable, 
                c.column_default, 
                c.ordinal_position,
                EXISTS (
                    SELECT 1 
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu 
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = c.table_schema
                      AND tc.table_name = c.table_name
                      AND kcu.column_name = c.column_name
                ) AS is_primary
            FROM information_schema.columns c
            WHERE c.table_schema=$1 AND c.table_name=$2
            ORDER BY c.ordinal_position
            """,
            schema,
            name,
        )
        return [
            TableColumn(
                name=c["column_name"],
                type_native=c["data_type"],
                type=infer_column_type(c["data_type"]),
                nullable=c["is_nullable"] == "YES",
                default=c["column_default"],
                ordinal=c["ordinal_position"] or 0,
                is_primary_key=bool(c["is_primary"]),
            )
            for c in rows
        ]

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        rows = await self._conn.fetch(
            """
            SELECT c.conname AS name,
                   rns.nspname AS ref_schema,
                   rcls.relname AS ref_table,
                   array_agg(att.attname ORDER BY u.ord) AS cols,
                   array_agg(ratt.attname ORDER BY u.ord) AS ref_cols
            FROM pg_constraint c
            JOIN pg_class cls ON cls.oid = c.conrelid
            JOIN pg_namespace ns ON ns.oid = cls.relnamespace
            JOIN pg_class rcls ON rcls.oid = c.confrelid
            JOIN pg_namespace rns ON rns.oid = rcls.relnamespace
            JOIN unnest(c.conkey, c.confkey) WITH ORDINALITY AS u(attnum, refattnum, ord)
                 ON true
            JOIN pg_attribute att
                 ON att.attrelid = c.conrelid AND att.attnum = u.attnum
            JOIN pg_attribute ratt
                 ON ratt.attrelid = c.confrelid AND ratt.attnum = u.refattnum
            WHERE c.contype = 'f' AND ns.nspname=$1 AND cls.relname=$2
            GROUP BY c.conname, rns.nspname, rcls.relname
            """,
            schema,
            name,
        )
        return [
            ForeignKey(
                name=fk["name"],
                columns=list(fk["cols"]),
                referenced_schema=fk["ref_schema"],
                referenced_table=fk["ref_table"],
                referenced_columns=list(fk["ref_cols"]),
            )
            for fk in rows
        ]

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        rows = await self._conn.fetch(
            """
            SELECT i.relname AS name, ix.indisunique AS uniq, ix.indisprimary AS pk,
                   array_agg(a.attname ORDER BY k.ord) AS cols
            FROM pg_index ix
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
            WHERE n.nspname=$1 AND t.relname=$2
            GROUP BY i.relname, ix.indisunique, ix.indisprimary
            """,
            schema,
            name,
        )
        return [
            Index(
                name=ix["name"],
                columns=list(ix["cols"]),
                unique=ix["uniq"],
                primary=ix["pk"],
            )
            for ix in rows
        ]

    def build_view(self, schema: str, name: str, kind: str, columns: list[TableColumn]) -> View:
        return View(
            name=name,
            schema_name=schema,
            columns=columns,
            kind=cast('Literal["view", "materialized_view"]', kind),
        )
