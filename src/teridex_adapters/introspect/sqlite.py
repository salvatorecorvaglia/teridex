"""SQLite schema introspector."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from teridex_adapters._introspect import SchemaIntrospector
from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import connection_id
from teridex_core.models.schema import ForeignKey, Index, TableColumn

if TYPE_CHECKING:
    import aiosqlite

    from teridex_adapters.sqlite_adapter import SQLiteAdapter


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SQLiteIntrospector(SchemaIntrospector):
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
        grouped = defaultdict(list)
        for fk_id, seq, ref_table, fcol, tcol, on_update, on_delete, _match in rows:
            grouped[fk_id].append((seq, ref_table, fcol, tcol, on_update, on_delete))

        fks = []
        for fk_id, parts in sorted(grouped.items()):
            parts.sort(key=lambda x: x[0])
            ref_table = parts[0][1]
            on_update = parts[0][4]
            on_delete = parts[0][5]
            cols = [p[2] for p in parts]
            ref_cols = [p[3] for p in parts]
            fks.append(
                ForeignKey(
                    name=f"fk_{name}_{fk_id}",
                    columns=cols,
                    referenced_table=ref_table,
                    referenced_columns=ref_cols,
                    on_delete=on_delete,
                    on_update=on_update,
                )
            )
        return fks

    async def fetch_indexes(self, schema: str, name: str) -> list[Index]:
        async with self._conn.execute(f"PRAGMA index_list({_quote_ident(name)})") as icur:
            idx_rows = await icur.fetchall()
        indexes: list[Index] = []
        for _seq, iname, unique, _origin, _partial in idx_rows:
            async with self._conn.execute(f"PRAGMA index_info({_quote_ident(iname)})") as iicur:
                icols = [r[2] for r in await iicur.fetchall()]
            indexes.append(Index(name=iname, columns=icols, unique=bool(unique)))
        return indexes
