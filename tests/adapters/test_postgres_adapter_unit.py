from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("asyncpg")

import asyncpg

from teridex_adapters.postgres_adapter import PostgresAdapter
from teridex_core.errors import AdapterError, QueryError
from teridex_core.models.query import QueryHandle, QueryStatus


def _adapter_with_statement(stmt: MagicMock) -> PostgresAdapter:
    adapter = PostgresAdapter()
    adapter._conn = MagicMock()
    adapter._conn.prepare = AsyncMock(return_value=stmt)
    return adapter


@pytest.mark.asyncio
async def test_dml_statement_is_executed_and_reports_its_status() -> None:
    stmt = MagicMock()
    stmt.get_attributes.return_value = []
    stmt.fetch = AsyncMock(return_value=[])
    stmt.get_statusmsg = MagicMock(return_value="UPDATE 1")
    adapter = _adapter_with_statement(stmt)

    handle = await adapter.execute("UPDATE t SET name = $1 WHERE id = $2", {"1": "Alice", "2": 42})
    batches = [batch async for batch in await adapter.stream(handle)]

    assert len(batches) == 1
    assert batches[0].columns == []
    assert batches[0].rows == []
    stmt.fetch.assert_called_once_with("Alice", 42)
    assert (await adapter.metadata(handle)).server_message == "UPDATE 1"


@pytest.mark.asyncio
async def test_select_streams_through_a_server_side_cursor() -> None:
    stmt = MagicMock()
    attr = MagicMock()
    attr.name = "id"
    attr.type.name = "integer"
    stmt.get_attributes.return_value = [attr]
    cursor = MagicMock()
    cursor.fetch = AsyncMock(side_effect=[[{"id": 42}], []])
    stmt.cursor = AsyncMock(return_value=cursor)
    adapter = _adapter_with_statement(stmt)

    handle = await adapter.execute("-- comment\nSELECT id FROM t WHERE name = $1", {"1": "Bob"})
    batches = [batch async for batch in await adapter.stream(handle)]

    assert len(batches) == 2
    assert batches[0].columns[0].name == "id"
    assert batches[0].rows == [(42,)]
    stmt.cursor.assert_called_once_with("Bob")


@pytest.mark.asyncio
async def test_execute_surfaces_a_bad_statement_like_every_other_adapter() -> None:
    """Preparing happens in ``execute()``, so SQL errors surface there."""
    adapter = PostgresAdapter()
    adapter._conn = MagicMock()
    adapter._conn.prepare = AsyncMock(side_effect=asyncpg.PostgresSyntaxError("boom"))

    with pytest.raises(QueryError):
        await adapter.execute("SELCT 1")


@pytest.mark.asyncio
async def test_stream_rejects_a_handle_execute_never_saw() -> None:
    adapter = PostgresAdapter()
    adapter._conn = MagicMock()
    stray = QueryHandle(connection_id="test", sql="SELECT 1")

    with pytest.raises(AdapterError, match="unknown handle"):
        await adapter.stream(stray)


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"name": "Alice"}, {"-1": "Alice"}, {"0": "Alice"}])
async def test_invalid_placeholder_keys_are_rejected(params: dict[str, object]) -> None:
    stmt = MagicMock()
    stmt.get_attributes.return_value = []
    adapter = _adapter_with_statement(stmt)

    handle = await adapter.execute("SELECT * FROM t WHERE name = $1", params)
    with pytest.raises(QueryError, match="invalid parameters"):
        await adapter.stream(handle)


@pytest.mark.asyncio
async def test_absurd_placeholder_index_is_refused_not_allocated() -> None:
    """``args`` is sized from the key, so an unbounded index is a memory bomb."""
    stmt = MagicMock()
    stmt.get_attributes.return_value = []
    adapter = _adapter_with_statement(stmt)

    handle = await adapter.execute("SELECT $1", {"999999999": "x"})
    with pytest.raises(QueryError, match="invalid parameters"):
        await adapter.stream(handle)


@pytest.mark.asyncio
async def test_parameter_gaps_are_filled_with_none() -> None:
    stmt = MagicMock()
    stmt.get_attributes.return_value = []
    stmt.fetch = AsyncMock(return_value=[])
    stmt.get_statusmsg = MagicMock(return_value="SELECT 1")
    adapter = _adapter_with_statement(stmt)

    handle = await adapter.execute("SELECT * FROM t WHERE name = $2", {"2": "Alice"})
    async for _ in await adapter.stream(handle):
        pass

    stmt.fetch.assert_called_once_with(None, "Alice")


@pytest.mark.asyncio
async def test_failed_execute_does_not_strand_the_active_query() -> None:
    adapter = PostgresAdapter()
    adapter._conn = MagicMock()
    adapter._conn.prepare = AsyncMock(side_effect=asyncpg.PostgresSyntaxError("boom"))

    with pytest.raises(QueryError):
        await adapter.execute("SELCT 1")
    assert adapter._active_query_id is None
    assert adapter._statements == {}


@pytest.mark.asyncio
async def test_streaming_a_result_forgets_its_prepared_statement() -> None:
    stmt = MagicMock()
    stmt.get_attributes.return_value = []
    stmt.fetch = AsyncMock(return_value=[])
    stmt.get_statusmsg = MagicMock(return_value="SELECT 0")
    adapter = _adapter_with_statement(stmt)

    handle = await adapter.execute("SELECT 1")
    assert adapter._statements
    async for _ in await adapter.stream(handle):
        pass
    assert adapter._statements == {}, "prepared statements accumulate per query"
    assert handle.status is QueryStatus.SUCCEEDED
