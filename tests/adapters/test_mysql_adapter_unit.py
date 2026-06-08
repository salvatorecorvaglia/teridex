from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("asyncmy")

from teridex_adapters.mysql_adapter import MySQLAdapter
from teridex_core.errors import QueryError


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
