from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from teridex_adapters.duckdb_adapter import DuckDBAdapter  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402


@pytest.mark.asyncio
async def test_duckdb_select() -> None:
    a = DuckDBAdapter()
    await a.connect(Dsn.parse("duckdb:///:memory:"))
    try:
        h = await a.execute("SELECT 42 AS answer, 'hi' AS greeting")
        rows: list[tuple] = []
        cols: list[str] = []
        async for batch in await a.stream(h):
            cols = [c.name for c in batch.columns] or cols
            rows.extend(batch.rows)
        assert cols == ["answer", "greeting"]
        rows = [r for r in rows if r]
        assert rows == [(42, "hi")]
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_duckdb_introspect_smoke() -> None:
    a = DuckDBAdapter()
    await a.connect(Dsn.parse("duckdb:///:memory:"))
    try:
        h = await a.execute("CREATE TABLE t (a INTEGER, b VARCHAR)")
        async for _ in await a.stream(h):
            pass
        snap = await a.introspect()
        assert any(obj.name == "t" for objs in snap.schemas.values() for obj in objs)
    finally:
        await a.close()
