from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.models.connection import Dsn
from teridex_engine.pool import ConnectionPool

if TYPE_CHECKING:
    from teridex_core.protocols.adapter import DatabaseAdapter


async def _factory(dsn: Dsn) -> DatabaseAdapter:
    a = SQLiteAdapter()
    await a.connect(dsn)
    return a


@pytest.mark.asyncio
async def test_pool_reuses_connection() -> None:
    pool = ConnectionPool(Dsn.parse("sqlite:///:memory:"), _factory, size=2)
    try:
        async with pool.acquire() as a1:
            assert await a1.ping()
        async with pool.acquire() as a2:
            assert await a2.ping()
    finally:
        await pool.close()
