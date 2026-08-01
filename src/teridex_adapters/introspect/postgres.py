"""PostgreSQL schema introspector."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from teridex_adapters._introspect import SchemaIntrospector
from teridex_adapters._typeinfer import infer_column_type
from teridex_adapters.base import connection_id
from teridex_core.models.schema import ForeignKey, Index, TableColumn, View

if TYPE_CHECKING:
    from typing import Literal

    import asyncpg

    from teridex_adapters.postgres_adapter import PostgresAdapter


class PostgresIntrospector(SchemaIntrospector):
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

    async def fetch_all_columns(self) -> dict[tuple[str, str], list[TableColumn]]:
        rows = await self._conn.fetch(
            """
            SELECT 
                c.table_schema,
                c.table_name,
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
            WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
            """
        )
        res: dict[tuple[str, str], list[TableColumn]] = {}
        for c in rows:
            key = (c["table_schema"], c["table_name"])
            res.setdefault(key, []).append(
                TableColumn(
                    name=c["column_name"],
                    type_native=c["data_type"],
                    type=infer_column_type(c["data_type"]),
                    nullable=c["is_nullable"] == "YES",
                    default=c["column_default"],
                    ordinal=c["ordinal_position"] or 0,
                    is_primary_key=bool(c["is_primary"]),
                )
            )
        return res

    async def fetch_all_foreign_keys(self) -> dict[tuple[str, str], list[ForeignKey]]:
        rows = await self._conn.fetch(
            """
            SELECT ns.nspname AS schema, cls.relname AS table_name,
                   c.conname AS name,
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
            WHERE c.contype = 'f' AND ns.nspname NOT IN ('pg_catalog', 'information_schema')
            GROUP BY ns.nspname, cls.relname, c.conname, rns.nspname, rcls.relname
            """
        )
        res: dict[tuple[str, str], list[ForeignKey]] = {}
        for fk in rows:
            key = (fk["schema"], fk["table_name"])
            res.setdefault(key, []).append(
                ForeignKey(
                    name=fk["name"],
                    columns=list(fk["cols"]),
                    referenced_schema=fk["ref_schema"],
                    referenced_table=fk["ref_table"],
                    referenced_columns=list(fk["ref_cols"]),
                )
            )
        return res

    async def fetch_all_indexes(self) -> dict[tuple[str, str], list[Index]]:
        rows = await self._conn.fetch(
            """
            SELECT n.nspname AS schema, t.relname AS table_name,
                   i.relname AS name, ix.indisunique AS uniq, ix.indisprimary AS pk,
                   array_agg(a.attname ORDER BY k.ord) AS cols
            FROM pg_index ix
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
            GROUP BY n.nspname, t.relname, i.relname, ix.indisunique, ix.indisprimary
            """
        )
        res: dict[tuple[str, str], list[Index]] = {}
        for ix in rows:
            key = (ix["schema"], ix["table_name"])
            res.setdefault(key, []).append(
                Index(
                    name=ix["name"],
                    columns=list(ix["cols"]),
                    unique=ix["uniq"],
                    primary=ix["pk"],
                )
            )
        return res

    def build_view(self, schema: str, name: str, kind: str, columns: list[TableColumn]) -> View:
        return View(
            name=name,
            schema_name=schema,
            columns=columns,
            kind=cast('Literal["view", "materialized_view"]', kind),
        )
