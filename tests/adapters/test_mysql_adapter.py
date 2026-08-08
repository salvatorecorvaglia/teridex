"""MySQL runs the shared adapter conformance suite.

Needs a server: either ``TERIDEX_MYSQL_DSN`` (see
``tests/scripts/test-integration.sh``) or a reachable Docker daemon, from which the
``mysql_dsn`` fixture starts a container.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("asyncmy")

from teridex_adapters.mysql_adapter import MySQLAdapter
from teridex_core.models.connection import Dsn
from tests.adapters._conformance import AdapterConformance, drain

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration


class TestMySQLConformance(AdapterConformance):
    create_table_sql = "CREATE TABLE teridex_conformance (id INT, name VARCHAR(32))"

    @pytest.fixture
    async def adapter(self, mysql_dsn: str) -> AsyncIterator[MySQLAdapter]:
        a = MySQLAdapter()
        await a.connect(Dsn.parse(mysql_dsn))
        try:
            await drain(a, "DROP TABLE IF EXISTS teridex_conformance")
            yield a
        finally:
            await drain(a, "DROP TABLE IF EXISTS teridex_conformance")
            await a.close()


@pytest.mark.asyncio
async def test_composite_foreign_key_introspection(mysql_dsn: str) -> None:
    dsn = Dsn.parse(mysql_dsn)
    adapter = MySQLAdapter()
    await adapter.connect(dsn)
    try:
        await drain(adapter, "DROP TABLE IF EXISTS fk_child")
        await drain(adapter, "DROP TABLE IF EXISTS fk_parent")
        await drain(adapter, "CREATE TABLE fk_parent (id1 INT, id2 INT, PRIMARY KEY (id1, id2))")
        await drain(
            adapter,
            "CREATE TABLE fk_child (c1 INT, c2 INT, "
            "FOREIGN KEY (c1, c2) REFERENCES fk_parent (id1, id2))",
        )

        fks = await adapter.fetch_foreign_keys(dsn.database or "test", "fk_child")
        assert len(fks) == 1
        assert fks[0].referenced_table == "fk_parent"
        assert fks[0].columns == ["c1", "c2"]
        assert fks[0].referenced_columns == ["id1", "id2"]
    finally:
        await drain(adapter, "DROP TABLE IF EXISTS fk_child")
        await drain(adapter, "DROP TABLE IF EXISTS fk_parent")
        await adapter.close()
