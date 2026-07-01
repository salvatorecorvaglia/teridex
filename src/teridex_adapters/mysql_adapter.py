"""MySQL adapter using asyncmy (native async)."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any, ClassVar

import asyncmy
from asyncmy import errors as asyncmy_errors

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

_PARAM_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class _MySQLTransaction:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> _MySQLTransaction:
        await self._conn.begin()
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


class MySQLAdapter(AbstractAdapter):
    name: ClassVar[str] = "mysql"
    schemes: ClassVar[tuple[str, ...]] = ("mysql",)

    def __init__(self) -> None:
        super().__init__()
        self._conn: Any = None
        self._cursors: dict[str, Any] = {}
        self._thread_id: int | None = None
        self._active_query_id: str | None = None
        self._lock = asyncio.Lock()

    async def _do_connect(self, dsn: Dsn) -> None:
        conn_kwargs: dict[str, Any] = {
            "user": dsn.username or "root",
            "password": dsn.password.get_secret_value() if dsn.password else "",
            "host": dsn.host or "localhost",
            "port": dsn.port or 3306,
            "database": dsn.database,
            "autocommit": True,
        }
        for k, v in dsn.params.items():
            if k == "port":
                continue
            if v.lower() == "true":
                conn_kwargs[k] = True
            elif v.lower() == "false":
                conn_kwargs[k] = False
            elif v.isdigit():
                conn_kwargs[k] = int(v)
            else:
                conn_kwargs[k] = v
        self._conn = await asyncmy.connect(**conn_kwargs)
        cur = self._conn.cursor()
        try:
            await cur.execute("SELECT CONNECTION_ID()")
            row = await cur.fetchone()
            self._thread_id = int(row[0]) if row else None
        finally:
            await cur.close()

    async def _do_close(self) -> None:
        for c in list(self._cursors.values()):
            with contextlib.suppress(Exception):
                await c.close()
        self._cursors.clear()
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._thread_id = None
        self._active_query_id = None

    async def cancel(self, handle: QueryHandle) -> None:
        await super().cancel(handle)
        if self._active_query_id != handle.query_id:
            return
        cur = self._cursors.pop(handle.query_id, None)
        # Live connection is busy; open side connection & issue KILL QUERY first.
        # This unblocks the statement so we can safely close the cursor later.
        if self._thread_id is not None and self._dsn is not None:
            dsn = self._dsn
            try:
                side_kwargs: dict[str, Any] = {
                    "user": dsn.username or "root",
                    "password": dsn.password.get_secret_value() if dsn.password else "",
                    "host": dsn.host or "localhost",
                    "port": dsn.port or 3306,
                    "database": dsn.database,
                    "autocommit": True,
                }
                for k, v in dsn.params.items():
                    if k == "port":
                        continue
                    if v.lower() == "true":
                        side_kwargs[k] = True
                    elif v.lower() == "false":
                        side_kwargs[k] = False
                    elif v.isdigit():
                        side_kwargs[k] = int(v)
                    else:
                        side_kwargs[k] = v
                side = await asyncio.wait_for(
                    asyncmy.connect(**side_kwargs),
                    timeout=5.0,
                )
                try:
                    scur = side.cursor()
                    try:
                        with contextlib.suppress(Exception):
                            await scur.execute(f"KILL QUERY {int(self._thread_id)}")
                    finally:
                        with contextlib.suppress(Exception):
                            await scur.close()
                finally:
                    with contextlib.suppress(Exception):
                        side.close()
            except Exception as exc:
                logger.warning(
                    "mysql_cancel_side_connect_failed",
                    query_id=handle.query_id,
                    error=str(exc),
                )

        # Now we can safely close the popped cursor
        if cur is not None:
            with contextlib.suppress(Exception):
                await cur.close()

    def _forget(self, handle: QueryHandle) -> None:
        super()._forget(handle)
        if self._active_query_id == handle.query_id:
            self._active_query_id = None

    async def reset(self) -> None:
        await super().reset()
        for cur in list(self._cursors.values()):
            with contextlib.suppress(Exception):
                await cur.close()
        self._cursors.clear()
        self._active_query_id = None

    async def ping(self) -> bool:
        if self._conn is None:
            return False
        try:
            cur = self._conn.cursor()
            await cur.execute("SELECT 1")
            await cur.close()
            return True
        except asyncmy_errors.Error:
            return False

    async def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryHandle:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        if params:
            for k in params:
                if not isinstance(k, str) or not _PARAM_NAME_RE.match(k):
                    raise QueryError(
                        f"mysql: invalid parameter name {k!r}. "
                        "Parameter names must be alphanumeric and start "
                        "with a letter or underscore.",
                        context={"sql": sql, "param_name": str(k)},
                    )
        handle = QueryHandle(
            connection_id=connection_id(self._conn),
            sql=sql,
            params=dict(params) if params else None,
        )
        handle.mark_running()
        self._active_query_id = handle.query_id
        cur = self._conn.cursor()
        try:
            # asyncmy uses the ``pyformat`` paramstyle: pass the mapping
            # directly so ``%(name)s`` placeholders bind by name.
            await cur.execute(sql, dict(params) if params else None)
        except asyncmy_errors.Error as exc:
            if self._cancel_event(handle).is_set():
                handle.mark_done(QueryStatus.CANCELLED)
                await cur.close()
                raise QueryCancelledError(
                    "query cancelled", context={"query_id": handle.query_id}
                ) from exc
            handle.mark_done(QueryStatus.FAILED)
            await cur.close()
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
            raise AdapterError("mysql: stream() called with unknown handle")

        async def _gen() -> AsyncIterator[ResultBatch]:
            description = cur.description or []
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
                    try:
                        rows = await cur.fetchmany(batch_size)
                    except asyncmy_errors.Error as exc:
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
                await cur.close()
                self._cursors.pop(handle.query_id, None)
                self._forget(handle)

        return _gen()

    async def begin(self) -> Transaction:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        return _MySQLTransaction(self._conn)

    async def introspect(self, *, lazy: bool = False) -> SchemaSnapshot:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        async with self._lock:
            return await _MySQLIntrospector(self, self._conn).build(lazy=lazy)

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        async with self._lock:
            return await _MySQLIntrospector(self, self._conn).fetch_columns(schema, name)

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        async with self._lock:
            return await _MySQLIntrospector(self, self._conn).fetch_foreign_keys(schema, name)

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        async with self._lock:
            return await _MySQLIntrospector(self, self._conn).fetch_indexes(schema, name)


class _MySQLIntrospector(SchemaIntrospector):
    def __init__(self, adapter: MySQLAdapter, conn: Any) -> None:
        self._adapter = adapter
        self._conn = conn

    def connection_id(self) -> str:
        return connection_id(self._conn)

    def database_name(self) -> str | None:
        return self._adapter._dsn.database if self._adapter._dsn else None

    async def _fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        cur = self._conn.cursor()
        try:
            await cur.execute(sql, params)
            return list(await cur.fetchall())
        finally:
            await cur.close()

    async def list_objects(self) -> list[tuple[str, str, str]]:
        rows = await self._fetch(
            "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE"
            " FROM information_schema.tables"
            " WHERE TABLE_SCHEMA NOT IN"
            " ('mysql','performance_schema','information_schema','sys')"
        )
        return [(schema, name, "view" if raw == "VIEW" else "table") for schema, name, raw in rows]

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        rows = await self._fetch(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, "
            "ORDINAL_POSITION, COLUMN_KEY FROM information_schema.columns "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
            (schema, name),
        )
        return [
            TableColumn(
                name=c[0],
                type_native=c[1],
                type=infer_column_type(c[1]),
                nullable=c[2] == "YES",
                default=c[3],
                ordinal=c[4] or 0,
                is_primary_key=(c[5] == "PRI"),
            )
            for c in rows
        ]

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        rows = await self._fetch(
            "SELECT CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME,"
            " REFERENCED_COLUMN_NAME, ORDINAL_POSITION FROM information_schema.key_column_usage"
            " WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s"
            " AND REFERENCED_TABLE_NAME IS NOT NULL"
            " ORDER BY CONSTRAINT_NAME, ORDINAL_POSITION",
            (schema, name),
        )
        grouped = defaultdict(list)
        for cn, col, ref_t, ref_c, ord_pos in rows:
            grouped[cn].append((ord_pos, col, ref_t, ref_c))

        fks = []
        for cn, parts in sorted(grouped.items()):
            parts.sort(key=lambda x: x[0])
            ref_t = parts[0][2]
            cols = [p[1] for p in parts]
            ref_cols = [p[3] for p in parts]
            fks.append(
                ForeignKey(
                    name=cn,
                    columns=cols,
                    referenced_table=ref_t,
                    referenced_columns=ref_cols,
                )
            )
        return fks

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        rows = await self._fetch(
            "SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE"
            " FROM information_schema.statistics"
            " WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s"
            " ORDER BY INDEX_NAME, SEQ_IN_INDEX",
            (schema, name),
        )
        by_idx: dict[str, dict[str, Any]] = {}
        for ix_name, col_name, non_unique in rows:
            entry = by_idx.setdefault(ix_name, {"cols": [], "unique": non_unique == 0})
            entry["cols"].append(col_name)
        return [
            Index(
                name=ix_name,
                columns=info["cols"],
                unique=info["unique"],
                primary=ix_name == "PRIMARY",
            )
            for ix_name, info in by_idx.items()
        ]
