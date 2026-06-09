"""MySQL conformance — gated on the ``TERIDEX_MYSQL_DSN`` env var."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("asyncmy")

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from teridex_adapters.mysql_adapter import MySQLAdapter
from teridex_core.models.connection import Dsn
from tests.adapters._conformance import (
    assert_cancel_raises,
    assert_connect_and_ping,
    assert_create_insert_select,
    assert_introspect_includes,
)

_DSN = os.getenv("TERIDEX_MYSQL_DSN", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DSN, reason="TERIDEX_MYSQL_DSN not set"),
]


@pytest.fixture
async def adapter() -> AsyncIterator[MySQLAdapter]:
    a = MySQLAdapter()
    await a.connect(Dsn.parse(_DSN))
    try:
        await _drain(a, "DROP TABLE IF EXISTS teridex_conformance")
        yield a
    finally:
        await _drain(a, "DROP TABLE IF EXISTS teridex_conformance")
        await a.close()


async def _drain(a: MySQLAdapter, sql: str) -> None:
    h = await a.execute(sql)
    async for _ in await a.stream(h):
        pass


async def test_ping(adapter: MySQLAdapter) -> None:
    await assert_connect_and_ping(adapter)


async def test_crud(adapter: MySQLAdapter) -> None:
    await assert_create_insert_select(
        adapter,
        create_sql="CREATE TABLE teridex_conformance (id INT, name VARCHAR(16))",
        insert_sql="INSERT INTO teridex_conformance VALUES (1, 'a'), (2, 'b')",
        select_sql="SELECT id, name FROM teridex_conformance ORDER BY id",
        expected_rows=[(1, "a"), (2, "b")],
    )


async def test_introspect(adapter: MySQLAdapter) -> None:
    await _drain(adapter, "CREATE TABLE teridex_conformance (id INT)")
    await assert_introspect_includes(adapter, "teridex_conformance")


async def test_cancel(adapter: MySQLAdapter) -> None:
    await assert_cancel_raises(adapter, "SELECT 1")
