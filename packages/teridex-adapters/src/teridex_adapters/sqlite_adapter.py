"""SQLite adapter using aiosqlite (native async)."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, ClassVar

import aiosqlite

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
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from teridex_core.models.connection import Dsn
    from teridex_core.protocols.adapter import Transaction

logger = get_logger(__name__)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class _SQLiteTransaction:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _SQLiteTransaction:
        await self._conn.execute("BEGIN")
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    async def commit(self) -> None:
        await self._conn.execute("COMMIT")

    async def rollback(self) -> None:
        await self._conn.execute("ROLLBACK")


class SQLiteAdapter(AbstractAdapter):
    name: ClassVar[str] = "sqlite"
    schemes: ClassVar[tuple[str, ...]] = ("sqlite",)

    def __init__(self) -> None:
        super().__init__()
        self._conn: aiosqlite.Connection | None = None
        self._cursors: dict[str, aiosqlite.Cursor] = {}

    async def _do_connect(self, dsn: Dsn) -> None:
        path = dsn.database or ":memory:"
        self._conn = await aiosqlite.connect(path, isolation_level=None)
        # WAL mode is fine on file dbs, no-op on memory.
        if path != ":memory:":
            with contextlib.suppress(aiosqlite.Error):
                await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

    async def _do_close(self) -> None:
        for cur in list(self._cursors.values()):
            with contextlib.suppress(aiosqlite.Error):
                await cur.close()
        self._cursors.clear()
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def ping(self) -> bool:
        if self._conn is None:
            return False
        try:
            await self._conn.execute("SELECT 1")
            return True
        except aiosqlite.Error:
            return False

    async def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryHandle:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        handle = QueryHandle(
            connection_id=connection_id(self._conn),
            sql=sql,
            params=dict(params) if params else None,
        )
        handle.mark_running()
        try:
            cur = await self._conn.execute(sql, params or {})
        except aiosqlite.Error as exc:
            handle.mark_done(QueryStatus.FAILED)
            raise QueryError(str(exc), context={"sql": sql}) from exc
        self._cursors[handle.query_id] = cur
        handle.mark_streaming()
        return handle

    async def stream(
        self, handle: QueryHandle, *, batch_size: int = 1000
    ) -> AsyncIterator[ResultBatch]:
        cancel = self._cancel_event(handle)
        if cancel.is_set():

            async def _gen_cancelled() -> AsyncIterator[ResultBatch]:
                handle.mark_done(QueryStatus.CANCELLED)
                if handle.query_id:
                    raise QueryCancelledError(
                        "query cancelled", context={"query_id": handle.query_id}
                    )
                yield ResultBatch(columns=[], rows=[], is_last=True)

            return _gen_cancelled()

        cur = self._cursors.get(handle.query_id)
        if cur is None:
            raise AdapterError("sqlite: stream() called with unknown handle")

        async def _gen() -> AsyncIterator[ResultBatch]:
            description: list[Any] = list(cur.description or [])
            columns = [
                Column(name=d[0], type=infer_column_type(None), type_native=None)
                for d in description
            ]
            self._set_metadata(
                handle,
                QueryMetadata(
                    column_names=[c.name for c in columns],
                    column_types=[],
                    affected_rows=cur.rowcount if cur.rowcount >= 0 else None,
                ),
            )
            if not columns:
                handle.mark_done(QueryStatus.SUCCEEDED)
                yield ResultBatch(columns=[], rows=[], is_last=True)
                return
            try:
                while True:
                    if cancel.is_set():
                        handle.mark_done(QueryStatus.CANCELLED)
                        raise QueryCancelledError(
                            "query cancelled", context={"query_id": handle.query_id}
                        )
                    rows = await cur.fetchmany(batch_size)
                    if not rows:
                        handle.mark_done(QueryStatus.SUCCEEDED)
                        yield ResultBatch(columns=columns, rows=[], is_last=True)
                        return
                    yield ResultBatch(columns=columns, rows=[tuple(r) for r in rows], is_last=False)
            finally:
                await cur.close()
                self._cursors.pop(handle.query_id, None)
                self._forget(handle)

        return _gen()

    async def cancel(self, handle: QueryHandle) -> None:
        await super().cancel(handle)
        cur = self._cursors.pop(handle.query_id, None)
        if cur is not None:
            with contextlib.suppress(Exception):
                await cur.close()
        # sqlite3.Connection.interrupt() is thread-safe and causes any
        # in-flight statement on the connection to raise OperationalError.
        # We bypass aiosqlite's async wrapper because it queues onto the
        # same worker thread that's currently blocked on the long query.
        if self._conn is None:
            return
        inner: Any = getattr(self._conn, "_conn", None)
        if inner is None:
            return
        with contextlib.suppress(Exception):
            inner.interrupt()

    async def reset(self) -> None:
        await super().reset()
        for cur in list(self._cursors.values()):
            with contextlib.suppress(Exception):
                await cur.close()
        self._cursors.clear()

    async def begin(self) -> Transaction:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        return _SQLiteTransaction(self._conn)

    async def introspect(self, *, lazy: bool = False) -> SchemaSnapshot:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        return await _SQLiteIntrospector(self, self._conn).build(lazy=lazy)

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        return await _SQLiteIntrospector(self, self._conn).fetch_columns(schema, name)

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        return await _SQLiteIntrospector(self, self._conn).fetch_foreign_keys(schema, name)

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        return await _SQLiteIntrospector(self, self._conn).fetch_indexes(schema, name)


class _SQLiteIntrospector(SchemaIntrospector):
    def __init__(self, adapter: SQLiteAdapter, conn: aiosqlite.Connection) -> None:
        self._adapter = adapter
        self._conn = conn

    def connection_id(self) -> str:
        return connection_id(self._conn)

    def database_name(self) -> str | None:
        return self._adapter._dsn.database if self._adapter._dsn else None

    async def list_objects(self) -> list[tuple[str, str, str]]:
        async with self._conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        return [("main", name, kind) for name, kind in rows]

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        async with self._conn.execute(f"PRAGMA table_info({_quote_ident(name)})") as ccur:
            rows = await ccur.fetchall()
        return [
            TableColumn(
                name=cname,
                type_native=ctype or "",
                type=infer_column_type(ctype),
                nullable=not notnull,
                default=dflt,
                is_primary_key=bool(pk),
                ordinal=cid,
            )
            for cid, cname, ctype, notnull, dflt, pk in rows
        ]

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        async with self._conn.execute(f"PRAGMA foreign_key_list({_quote_ident(name)})") as fcur:
            rows = await fcur.fetchall()
        return [
            ForeignKey(
                name=f"fk_{name}_{fk_id}",
                columns=[fcol],
                referenced_table=ref_table,
                referenced_columns=[tcol],
                on_delete=on_delete,
                on_update=on_update,
            )
            for fk_id, _seq, ref_table, fcol, tcol, on_update, on_delete, _match in rows
        ]

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        async with self._conn.execute(f"PRAGMA index_list({_quote_ident(name)})") as icur:
            idx_rows = await icur.fetchall()
        indexes: list[Index] = []
        for _seq, iname, unique, _origin, _partial in idx_rows:
            async with self._conn.execute(f"PRAGMA index_info({_quote_ident(iname)})") as iicur:
                icols = [r[2] for r in await iicur.fetchall()]
            indexes.append(Index(name=iname, columns=icols, unique=bool(unique)))
        return indexes
