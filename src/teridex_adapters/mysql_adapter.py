"""MySQL adapter using asyncmy (native async)."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, Any, ClassVar

import asyncmy
from asyncmy import errors as asyncmy_errors

from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import AbstractAdapter, connection_id
from teridex_adapters.introspect.mysql import MySQLIntrospector
from teridex_core.errors import (
    AdapterConnectionError,
    AdapterError,
    QueryCancelledError,
    QueryError,
)
from teridex_core.logging import get_logger
from teridex_core.models.query import QueryHandle, QueryMetadata, QueryStatus
from teridex_core.models.result import Column, ResultBatch

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from teridex_core.models.connection import Dsn
    from teridex_core.models.schema import (
        ForeignKey,
        Index,
        SchemaSnapshot,
        TableColumn,
    )
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
        try:
            self._conn = await asyncmy.connect(**conn_kwargs)
            cur = self._conn.cursor()
            try:
                await cur.execute("SELECT CONNECTION_ID()")
                row = await cur.fetchone()
                self._thread_id = int(row[0]) if row else None
            finally:
                await cur.close()
        except Exception as exc:
            raise AdapterConnectionError(
                f"mysql: connection failed: {exc}",
                context={"dsn": dsn.render(mask_password=True)},
            ) from exc

    async def _do_close(self) -> None:
        for c in list(self._cursors.values()):
            with contextlib.suppress(Exception):
                await c.close()
        self._cursors.clear()
        if self._conn is not None:
            await self._conn.ensure_closed()
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
                        await side.ensure_closed()
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
            return await MySQLIntrospector(self, self._conn).build(lazy=lazy)

    async def fetch_columns(self, schema: str, name: str) -> list[TableColumn]:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        async with self._lock:
            return await MySQLIntrospector(self, self._conn).fetch_columns(schema, name)

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        async with self._lock:
            return await MySQLIntrospector(self, self._conn).fetch_foreign_keys(schema, name)

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        if self._conn is None:
            raise AdapterError("mysql: not connected")
        async with self._lock:
            return await MySQLIntrospector(self, self._conn).fetch_indexes(schema, name)
