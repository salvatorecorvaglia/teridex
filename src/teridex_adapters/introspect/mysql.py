"""MySQL schema introspector."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from teridex_adapters._introspect import SchemaIntrospector
from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import connection_id
from teridex_core.models.schema import ForeignKey, Index, TableColumn

if TYPE_CHECKING:
    from teridex_adapters.mysql_adapter import MySQLAdapter


class MySQLIntrospector(SchemaIntrospector):
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
