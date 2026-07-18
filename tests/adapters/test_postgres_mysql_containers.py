from __future__ import annotations

import pytest

from teridex_adapters.mysql_adapter import MySQLAdapter
from teridex_adapters.postgres_adapter import PostgresAdapter
from teridex_core.models.connection import Dsn

try:
    from testcontainers.core.container import DockerClient
    from testcontainers.mysql import MySqlContainer
    from testcontainers.postgres import PostgresContainer

    DockerClient().client.ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker is not available/running")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_container_introspection() -> None:
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn_str = pg.get_connection_url()
        if "://" in dsn_str:
            scheme_part, rest = dsn_str.split("://", 1)
            if "+" in scheme_part:
                dsn_str = f"{scheme_part.split('+', 1)[0]}://{rest}"

        adapter = PostgresAdapter()
        await adapter.connect(Dsn.parse(dsn_str))
        try:
            assert adapter._conn is not None
            # Create a table and add a composite foreign key
            async with await adapter.begin():
                await adapter._conn.execute(
                    "CREATE TABLE parent (id1 INT, id2 INT, PRIMARY KEY (id1, id2))"
                )
                await adapter._conn.execute(
                    "CREATE TABLE child ("
                    "  c1 INT, c2 INT, "
                    "  FOREIGN KEY (c1, c2) REFERENCES parent (id1, id2)"
                    ")"
                )

            # Introspect foreign keys
            fks = await adapter.fetch_foreign_keys("public", "child")
            assert len(fks) == 1
            assert fks[0].referenced_table == "parent"
            assert set(fks[0].columns) == {"c1", "c2"}
            assert set(fks[0].referenced_columns) == {"id1", "id2"}
        finally:
            await adapter.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mysql_container_introspection() -> None:
    with MySqlContainer("mysql:8.0") as mysql:
        dsn_str = mysql.get_connection_url()
        if "://" in dsn_str:
            scheme_part, rest = dsn_str.split("://", 1)
            if "+" in scheme_part:
                dsn_str = f"{scheme_part.split('+', 1)[0]}://{rest}"

        adapter = MySQLAdapter()
        await adapter.connect(Dsn.parse(dsn_str))
        try:
            cur = adapter._conn.cursor()
            try:
                await cur.execute("CREATE TABLE parent (id1 INT, id2 INT, PRIMARY KEY (id1, id2))")
                await cur.execute(
                    "CREATE TABLE child ("
                    "  c1 INT, c2 INT, "
                    "  FOREIGN KEY (c1, c2) REFERENCES parent (id1, id2)"
                    ")"
                )
            finally:
                await cur.close()

            # Introspect foreign keys
            db_name = Dsn.parse(dsn_str).database or "test"
            fks = await adapter.fetch_foreign_keys(db_name, "child")
            assert len(fks) == 1
            assert fks[0].referenced_table == "parent"
            assert set(fks[0].columns) == {"c1", "c2"}
            assert set(fks[0].referenced_columns) == {"id1", "id2"}
        finally:
            await adapter.close()
