"""PostgreSQL adapter using asyncpg directly (native async, server-side cursors)."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg

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
        self._pending: dict[str, str] = {}  # query_id -> sql (for streaming via cursor)
        self._backend_pid: int | None = None

    async def _do_connect(self, dsn: Dsn) -> None:
        self._conn = await asyncpg.connect(
            user=dsn.username,
            password=dsn.password,
            host=dsn.host or "localhost",
            port=dsn.port or 5432,
            database=dsn.database,
        )
        self._backend_pid = await self._conn.fetchval("SELECT pg_backend_pid()")

    async def _do_close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._backend_pid = None

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
            connection_id=hex(id(self._conn)),
            sql=sql,
            params=dict(params) if params else None,
        )
        handle.mark_running()
        # We defer actual execution to stream() so we can use a server-side cursor
        # for SELECTs and ``execute`` for DML.
        self._pending[handle.query_id] = sql
        handle.mark_streaming()
        return handle

    async def stream(
        self, handle: QueryHandle, *, batch_size: int = 1000
    ) -> AsyncIterator[ResultBatch]:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        sql = self._pending.pop(handle.query_id, None)
        if sql is None:
            raise AdapterError("postgres: stream() called with unknown handle")
        cancel = self._cancel_event(handle)
        conn = self._conn

        async def _gen() -> AsyncIterator[ResultBatch]:
            stripped = sql.lstrip().lower()
            if not stripped.startswith(("select", "with", "show", "explain")):
                # DML / DDL — execute and finalize.
                try:
                    status = await conn.execute(sql)
                except asyncpg.PostgresError as exc:
                    handle.mark_done(QueryStatus.FAILED)
                    raise QueryError(str(exc), context={"sql": sql}) from exc
                handle.mark_done(QueryStatus.SUCCEEDED)
                self._set_metadata(
                    handle, QueryMetadata(server_message=status, column_names=[], column_types=[])
                )
                yield ResultBatch(columns=[], rows=[], is_last=True)
                return

            try:
                async with conn.transaction():
                    cur = conn.cursor(sql)
                    first = await cur.fetch(1)
                    if not first:
                        # empty result set — derive columns from a prepared stmt
                        stmt = await conn.prepare(sql)
                        attrs = stmt.get_attributes()
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
                        handle.mark_done(QueryStatus.SUCCEEDED)
                        yield ResultBatch(columns=columns, rows=[], is_last=True)
                        return
                    record0 = first[0]
                    columns = [
                        Column(name=k, type=infer_column_type(None), type_native=None)
                        for k in record0
                    ]
                    self._set_metadata(
                        handle,
                        QueryMetadata(column_names=[c.name for c in columns], column_types=[]),
                    )
                    yield ResultBatch(
                        columns=columns,
                        rows=[tuple(r.values()) for r in first],
                        is_last=False,
                    )
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
                handle.mark_done(QueryStatus.FAILED)
                raise QueryError(str(exc), context={"sql": sql}) from exc

        return _gen()

    async def cancel(self, handle: QueryHandle) -> None:
        await super().cancel(handle)
        # The live connection is busy running the user's query, so we can't
        # use it to issue pg_cancel_backend — open a short-lived side
        # connection instead and target the saved backend PID.
        if self._backend_pid is None or self._dsn is None:
            return
        dsn = self._dsn
        try:
            side = await asyncpg.connect(
                user=dsn.username,
                password=dsn.password,
                host=dsn.host or "localhost",
                port=dsn.port or 5432,
                database=dsn.database,
            )
        except (asyncpg.PostgresError, OSError) as exc:
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

    async def begin(self) -> Transaction:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        return _PostgresTransaction(self._conn)

    async def introspect(self) -> SchemaSnapshot:
        if self._conn is None:
            raise AdapterError("postgres: not connected")
        conn = self._conn
        schemas: dict[str, list[SchemaObject]] = {}

        rows = await conn.fetch(
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
        for r in rows:
            schema_name = r["schema_name"]
            name = r["name"]
            kind = r["kind"]
            col_rows = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, column_default, ordinal_position
                FROM information_schema.columns
                WHERE table_schema=$1 AND table_name=$2
                ORDER BY ordinal_position
                """,
                schema_name,
                name,
            )
            columns = [
                TableColumn(
                    name=c["column_name"],
                    type_native=c["data_type"],
                    type=infer_column_type(c["data_type"]),
                    nullable=c["is_nullable"] == "YES",
                    default=c["column_default"],
                    ordinal=c["ordinal_position"] or 0,
                )
                for c in col_rows
            ]
            fks: list[ForeignKey] = []
            indexes: list[Index] = []
            if kind == "table":
                fk_rows = await conn.fetch(
                    """
                    SELECT conname,
                           pg_get_constraintdef(c.oid) AS def,
                           array_agg(att.attname ORDER BY u.ord) AS cols
                    FROM pg_constraint c
                    JOIN pg_class cls ON cls.oid = c.conrelid
                    JOIN pg_namespace ns ON ns.oid = cls.relnamespace
                    JOIN unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord) ON true
                    JOIN pg_attribute att ON att.attrelid = c.conrelid AND att.attnum = u.attnum
                    WHERE c.contype = 'f' AND ns.nspname=$1 AND cls.relname=$2
                    GROUP BY conname, c.oid
                    """,
                    schema_name,
                    name,
                )
                for fk in fk_rows:
                    fks.append(
                        ForeignKey(
                            name=fk["conname"],
                            columns=list(fk["cols"]),
                            referenced_table=fk["def"],
                            referenced_columns=[],
                        )
                    )
                idx_rows = await conn.fetch(
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
                    schema_name,
                    name,
                )
                for ix in idx_rows:
                    indexes.append(
                        Index(
                            name=ix["name"],
                            columns=list(ix["cols"]),
                            unique=ix["uniq"],
                            primary=ix["pk"],
                        )
                    )
            obj: SchemaObject
            if kind in {"view", "materialized_view"}:
                obj = View(name=name, schema_name=schema_name, columns=columns, kind=kind)
            else:
                obj = Table(
                    name=name,
                    schema_name=schema_name,
                    columns=columns,
                    foreign_keys=fks,
                    indexes=indexes,
                )
            schemas.setdefault(schema_name, []).append(obj)
        return SchemaSnapshot(
            connection_id=hex(id(conn)),
            database=self._dsn.database if self._dsn else None,
            schemas=schemas,
        )
