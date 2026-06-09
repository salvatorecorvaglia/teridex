from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("asyncpg")

from teridex_adapters.postgres_adapter import PostgresAdapter
from teridex_core.models.query import QueryHandle


@pytest.mark.asyncio
async def test_postgres_adapter_parameters_and_classification() -> None:
    adapter = PostgresAdapter()
    adapter._conn = MagicMock()

    # 1. Test DML query classification (no attributes returned by prepare)
    stmt_mock = MagicMock()
    stmt_mock.get_attributes.return_value = []
    stmt_mock.fetch = AsyncMock(return_value=[])
    stmt_mock.get_statusmsg = MagicMock(return_value="UPDATE 1")
    adapter._conn.prepare = AsyncMock(return_value=stmt_mock)

    handle = QueryHandle(
        connection_id="test",
        sql="UPDATE t SET name = $1 WHERE id = $2",
        params={"1": "Alice", "2": 42},
    )

    batches = []
    async for batch in await adapter.stream(handle):
        batches.append(batch)

    assert len(batches) == 1
    assert batches[0].columns == []
    assert batches[0].rows == []
    stmt_mock.fetch.assert_called_once_with("Alice", 42)
    stmt_mock.get_statusmsg.assert_called_once()

    # 2. Test DQL / RETURNING query classification (attributes returned by prepare)
    stmt_mock_dql = MagicMock()
    attr1 = MagicMock()
    attr1.name = "id"
    attr1.type.name = "integer"
    stmt_mock_dql.get_attributes.return_value = [attr1]

    cursor_mock = MagicMock()
    cursor_mock.fetch = AsyncMock(side_effect=[[{"id": 42}], []])
    stmt_mock_dql.cursor = AsyncMock(return_value=cursor_mock)
    adapter._conn.prepare = AsyncMock(return_value=stmt_mock_dql)

    handle_dql = QueryHandle(
        connection_id="test",
        sql="-- comment\nSELECT id FROM t WHERE name = $1",
        params={"1": "Bob"},
    )

    batches_dql = []
    async for batch in await adapter.stream(handle_dql):
        batches_dql.append(batch)

    assert len(batches_dql) == 2
    assert batches_dql[0].columns[0].name == "id"
    assert batches_dql[0].rows == [(42,)]
    stmt_mock_dql.cursor.assert_called_once_with("Bob")
