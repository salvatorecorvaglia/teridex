"""DuckDB schema introspector."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from teridex_adapters._introspect import SchemaIntrospector
from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import connection_id
from teridex_core.models.schema import ForeignKey, Index, TableColumn

if TYPE_CHECKING:
    import duckdb

    from teridex_core.models.connection import Dsn


class DuckDBIntrospector(SchemaIntrospector):
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
                "SELECT "
                "    c.column_name, "
                "    c.data_type, "
                "    c.is_nullable, "
                "    c.column_default, "
                "    c.ordinal_position, "
                "    EXISTS ( "
                "        SELECT 1 "
                "        FROM information_schema.table_constraints tc "
                "        JOIN information_schema.key_column_usage kcu "
                "          ON tc.constraint_name = kcu.constraint_name "
                "         AND tc.table_schema = kcu.table_schema "
                "        WHERE tc.constraint_type = 'PRIMARY KEY' "
                "          AND tc.table_schema = c.table_schema "
                "          AND tc.table_name = c.table_name "
                "          AND kcu.column_name = c.column_name "
                "    ) AS is_primary "
                "FROM information_schema.columns c "
                "WHERE c.table_schema=? AND c.table_name=? "
                "ORDER BY c.ordinal_position",
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
                    is_primary_key=bool(c[5]),
                )
                for c in cols
            ]

        async with self._lock:
            return await asyncio.to_thread(_fetch)

    async def fetch_foreign_keys(self, schema: str, name: str) -> list[ForeignKey]:
        conn = self._conn

        def _fetch() -> list[ForeignKey]:
            rows = conn.execute(
                "SELECT constraint_name, constraint_column_names, "
                "referenced_table, referenced_column_names "
                "FROM duckdb_constraints() "
                "WHERE schema_name = ? AND table_name = ? AND constraint_type = 'FOREIGN KEY'",
                [schema, name],
            ).fetchall()
            return [
                ForeignKey(
                    name=row[0] or f"fk_{name}_{i}",
                    columns=list(row[1]),
                    referenced_table=row[2],
                    referenced_columns=list(row[3]),
                )
                for i, row in enumerate(rows)
            ]

        async with self._lock:
            return await asyncio.to_thread(_fetch)

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        conn = self._conn

        def _fetch() -> list[Index]:
            rows = conn.execute(
                "SELECT index_name, expressions, is_unique, is_primary "
                "FROM duckdb_indexes() "
                "WHERE schema_name = ? AND table_name = ?",
                [schema, name],
            ).fetchall()
            indexes = []
            for idx_name, exprs, is_uniq, is_pri in rows:
                cols = [c.strip() for c in exprs.strip("[]").split(",") if c.strip()]
                indexes.append(
                    Index(
                        name=idx_name,
                        columns=cols,
                        unique=bool(is_uniq),
                        primary=bool(is_pri),
                    )
                )
            return indexes

        async with self._lock:
            return await asyncio.to_thread(_fetch)
