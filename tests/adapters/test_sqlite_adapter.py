from __future__ import annotations

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.errors import QueryCancelledError
from teridex_core.models.connection import Dsn


@pytest.mark.asyncio
async def test_connect_ping_close() -> None:
    a = SQLiteAdapter()
    await a.connect(Dsn.parse("sqlite:///:memory:"))
    assert await a.ping() is True
    await a.close()


@pytest.mark.asyncio
async def test_execute_and_stream() -> None:
    a = SQLiteAdapter()
    await a.connect(Dsn.parse("sqlite:///:memory:"))
    try:
        await a.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        h = await a.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
        async for _ in await a.stream(h):
            pass
        h = await a.execute("SELECT id, name FROM t ORDER BY id")
        rows: list[tuple] = []
        cols: list[str] = []
        async for batch in await a.stream(h, batch_size=10):
            cols = [c.name for c in batch.columns] or cols
            rows.extend(batch.rows)
        assert cols == ["id", "name"]
        # last batch may be empty terminator
        rows = [r for r in rows if r]
        assert rows == [(1, "a"), (2, "b")]
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_introspect_tables_and_indexes() -> None:
    a = SQLiteAdapter()
    await a.connect(Dsn.parse("sqlite:///:memory:"))
    try:
        h = await a.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE)"
        )
        async for _ in await a.stream(h):
            pass
        h = await a.execute("CREATE INDEX ix_email ON users(email)")
        async for _ in await a.stream(h):
            pass
        snap = await a.introspect()
        assert "main" in snap.schemas
        users = next(o for o in snap.schemas["main"] if o.name == "users")
        col_names = [c.name for c in users.columns]
        assert "id" in col_names
        assert "email" in col_names
        assert any(i.name == "ix_email" for i in users.indexes)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_cancel_sets_status() -> None:
    a = SQLiteAdapter()
    await a.connect(Dsn.parse("sqlite:///:memory:"))
    try:
        h = await a.execute("SELECT 1")
        await a.cancel(h)
        # consume stream — should raise cancelled
        with pytest.raises(QueryCancelledError):
            async for _ in await a.stream(h):
                pass
    finally:
        await a.close()
