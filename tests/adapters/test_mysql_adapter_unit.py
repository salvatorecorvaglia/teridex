from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("asyncmy")

import asyncmy
from asyncmy import errors as asyncmy_errors
from asyncmy.constants import FIELD_TYPE

from teridex_adapters.mysql_adapter import (
    _FIELD_TYPE_NAMES,
    MySQLAdapter,
    _describe_columns,
)
from teridex_core.errors import AdapterError, QueryCancelledError, QueryError
from teridex_core.models.connection import Dsn
from teridex_core.models.query import QueryHandle, QueryStatus
from teridex_core.models.result import ColumnType


def _adapter_with_cursor(cursor: MagicMock) -> MySQLAdapter:
    adapter = MySQLAdapter()
    adapter._conn = MagicMock()
    adapter._conn.cursor.return_value = cursor
    return adapter


@pytest.mark.asyncio
async def test_mysql_adapter_param_key_validation() -> None:
    adapter = MySQLAdapter()
    adapter._conn = MagicMock()
    cursor_mock = MagicMock()
    cursor_mock.execute = AsyncMock()
    adapter._conn.cursor.return_value = cursor_mock

    # Valid parameter keys should not raise
    await adapter.execute("SELECT %(name)s", {"name": "test", "_id": 123})
    cursor_mock.execute.assert_called_once_with("SELECT %(name)s", {"name": "test", "_id": 123})

    # Invalid keys should raise QueryError
    with pytest.raises(QueryError) as exc_info:
        await adapter.execute("SELECT %(name)s", {"invalid-key": "test"})
    assert "invalid parameter name" in str(exc_info.value)

    with pytest.raises(QueryError) as exc_info:
        await adapter.execute("SELECT %(name)s", {"key'with;sql": "test"})
    assert "invalid parameter name" in str(exc_info.value)

    # Non-string keys should also raise QueryError
    with pytest.raises(QueryError) as exc_info:
        await adapter.execute("SELECT %(name)s", {123: "test"})  # type: ignore
    assert "invalid parameter name" in str(exc_info.value)


@pytest.mark.asyncio
async def test_select_streams_rows_through_the_cursor() -> None:
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.description = [("id", FIELD_TYPE.LONG)]
    cursor.rowcount = -1
    cursor.fetchmany = AsyncMock(side_effect=[[(1,)], []])
    cursor.close = AsyncMock()
    adapter = _adapter_with_cursor(cursor)

    handle = await adapter.execute("SELECT id FROM t")
    batches = [batch async for batch in await adapter.stream(handle)]

    assert len(batches) == 2
    assert batches[0].columns[0].name == "id"
    assert batches[0].rows == [(1,)]
    assert batches[1].is_last
    assert handle.status is QueryStatus.SUCCEEDED
    cursor.close.assert_called_once()


@pytest.mark.asyncio
async def test_execute_surfaces_a_bad_statement_like_every_other_adapter() -> None:
    cursor = MagicMock()
    cursor.execute = AsyncMock(side_effect=asyncmy_errors.OperationalError("boom"))
    cursor.close = AsyncMock()
    adapter = _adapter_with_cursor(cursor)

    with pytest.raises(QueryError):
        await adapter.execute("SELCT 1")
    cursor.close.assert_called_once()


@pytest.mark.asyncio
async def test_stream_rejects_a_handle_execute_never_saw() -> None:
    adapter = MySQLAdapter()
    adapter._conn = MagicMock()
    stray = QueryHandle(connection_id="test", sql="SELECT 1")

    with pytest.raises(AdapterError, match="unknown handle"):
        await adapter.stream(stray)


@pytest.mark.asyncio
async def test_fetchmany_error_mid_stream_is_wrapped_as_query_error() -> None:
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.description = [("id", FIELD_TYPE.LONG)]
    cursor.rowcount = -1
    cursor.fetchmany = AsyncMock(side_effect=asyncmy_errors.OperationalError("lost connection"))
    cursor.close = AsyncMock()
    adapter = _adapter_with_cursor(cursor)

    handle = await adapter.execute("SELECT id FROM t")
    with pytest.raises(QueryError):
        async for _ in await adapter.stream(handle):
            pass


@pytest.mark.asyncio
async def test_cancel_flag_takes_precedence_over_driver_error_while_streaming() -> None:
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.description = [("id", FIELD_TYPE.LONG)]
    cursor.rowcount = -1
    cursor.close = AsyncMock()
    adapter = _adapter_with_cursor(cursor)

    handle = await adapter.execute("SELECT id FROM t")

    async def _fetchmany(_n: int) -> list[tuple[int]]:
        await adapter.cancel(handle)
        raise asyncmy_errors.OperationalError("query killed")

    cursor.fetchmany = _fetchmany

    with pytest.raises(QueryCancelledError):
        async for _ in await adapter.stream(handle):
            pass


@pytest.mark.asyncio
async def test_cancel_issues_kill_query_on_a_side_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    adapter = _adapter_with_cursor(cursor)
    adapter._dsn = Dsn.parse("mysql://user:pw@localhost/db")
    adapter._thread_id = 99

    handle = await adapter.execute("SELECT SLEEP(3)")

    side_cursor = MagicMock()
    side_cursor.execute = AsyncMock()
    side_cursor.close = AsyncMock()
    side_conn = MagicMock()
    side_conn.cursor.return_value = side_cursor
    side_conn.ensure_closed = AsyncMock()
    connect = AsyncMock(return_value=side_conn)
    monkeypatch.setattr(asyncmy, "connect", connect)

    await adapter.cancel(handle)

    side_cursor.execute.assert_called_once_with("KILL QUERY 99")
    side_conn.ensure_closed.assert_called_once()


@pytest.mark.asyncio
async def test_reset_rolls_back_and_clears_in_flight_cursors() -> None:
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.close = AsyncMock()
    adapter = _adapter_with_cursor(cursor)
    adapter._conn.rollback = AsyncMock()

    await adapter.execute("SELECT 1")
    assert adapter._cursors

    await adapter.reset()

    cursor.close.assert_called_once()
    adapter._conn.rollback.assert_called_once()
    assert adapter._cursors == {}
    assert adapter._active_query_id is None


def test_tinyint_is_typed_as_integer_not_string() -> None:
    """``FIELD_TYPE.CHAR`` aliases ``FIELD_TYPE.TINY`` — the map must not confuse them.

    Both constants are ``1``. A ``CHAR: STRING`` entry written after
    ``TINY: INTEGER`` silently overwrote it, so every TINYINT column — and
    therefore every BOOLEAN, which MySQL stores as TINYINT(1) — was reported to
    the UI and to CSV/JSON export as a string.
    """
    assert FIELD_TYPE.CHAR == FIELD_TYPE.TINY, "precondition: the driver still aliases these"

    columns = _describe_columns([("flag", FIELD_TYPE.TINY, None, None, None, None, None)])

    assert columns[0].type is ColumnType.INTEGER
    assert columns[0].type_native == "TINY"


def test_real_string_columns_are_still_typed_as_string() -> None:
    """Dropping the aliased CHAR entry must not untype genuine text columns."""
    description = [
        ("a", FIELD_TYPE.STRING, None, None, None, None, None),
        ("b", FIELD_TYPE.VAR_STRING, None, None, None, None, None),
        ("c", FIELD_TYPE.VARCHAR, None, None, None, None, None),
    ]

    assert [c.type for c in _describe_columns(description)] == [ColumnType.STRING] * 3


def test_aliased_field_type_names_resolve_canonically() -> None:
    """``INTERVAL`` aliases ``YEAR`` (both 13); the canonical name must win."""
    assert _FIELD_TYPE_NAMES[FIELD_TYPE.YEAR] == "YEAR"
    assert _FIELD_TYPE_NAMES[FIELD_TYPE.TINY] == "TINY"
