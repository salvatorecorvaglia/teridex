"""SQLite adapter using aiosqlite (native async)."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, ClassVar

import aiosqlite

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
        await self._conn.commit()

    async def rollback(self) -> None:
        await self._conn.rollback()


class SQLiteAdapter(AbstractAdapter):
    name: ClassVar[str] = "sqlite"
    schemes: ClassVar[tuple[str, ...]] = ("sqlite",)

    def __init__(self) -> None:
        super().__init__()
        self._conn: aiosqlite.Connection | None = None
        self._cursors: dict[str, aiosqlite.Cursor] = {}

    async def _do_connect(self, dsn: Dsn) -> None:
        path = dsn.database or ":memory:"
        self._conn = await aiosqlite.connect(path)
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
            connection_id=hex(id(self._conn)),
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
        cur = self._cursors.get(handle.query_id)
        if cur is None:
            raise AdapterError("sqlite: stream() called with unknown handle")
        cancel = self._cancel_event(handle)

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

        return _gen()

    async def begin(self) -> Transaction:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        return _SQLiteTransaction(self._conn)

    async def introspect(self) -> SchemaSnapshot:
        if self._conn is None:
            raise AdapterError("sqlite: not connected")
        conn = self._conn
        objects: list[SchemaObject] = []
        async with conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        for name, kind in rows:
            cols: list[TableColumn] = []
            async with conn.execute(f"PRAGMA table_info({_quote_ident(name)})") as ccur:
                for cid, cname, ctype, notnull, dflt, pk in await ccur.fetchall():
                    cols.append(
                        TableColumn(
                            name=cname,
                            type_native=ctype or "",
                            type=infer_column_type(ctype),
                            nullable=not notnull,
                            default=dflt,
                            is_primary_key=bool(pk),
                            ordinal=cid,
                        )
                    )
            fks: list[ForeignKey] = []
            async with conn.execute(f"PRAGMA foreign_key_list({_quote_ident(name)})") as fcur:
                for (
                    fk_id,
                    _seq,
                    ref_table,
                    fcol,
                    tcol,
                    on_update,
                    on_delete,
                    _match,
                ) in await fcur.fetchall():
                    fks.append(
                        ForeignKey(
                            name=f"fk_{name}_{fk_id}",
                            columns=[fcol],
                            referenced_table=ref_table,
                            referenced_columns=[tcol],
                            on_delete=on_delete,
                            on_update=on_update,
                        )
                    )
            indexes: list[Index] = []
            async with conn.execute(f"PRAGMA index_list({_quote_ident(name)})") as icur:
                idx_rows = await icur.fetchall()
            for _seq, iname, unique, _origin, _partial in idx_rows:
                async with conn.execute(f"PRAGMA index_info({_quote_ident(iname)})") as iicur:
                    icols = [r[2] for r in await iicur.fetchall()]
                indexes.append(Index(name=iname, columns=icols, unique=bool(unique)))
            obj: SchemaObject
            if kind == "view":
                obj = View(name=name, schema_name="main", columns=cols)
            else:
                obj = Table(
                    name=name,
                    schema_name="main",
                    columns=cols,
                    foreign_keys=fks,
                    indexes=indexes,
                )
            objects.append(obj)
        return SchemaSnapshot(
            connection_id=hex(id(conn)),
            database=self._dsn.database if self._dsn else None,
            schemas={"main": objects},
        )
