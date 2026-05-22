from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from teridex_engine.history import HistoryEntry, QueryHistory

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_history_round_trip(tmp_path: Path) -> None:
    h = QueryHistory(tmp_path / "h.db", max_entries=3)
    await h.open()
    try:
        for i in range(5):
            await h.add(
                HistoryEntry(
                    query_id=f"q{i}",
                    connection_label="sqlite:///:memory:",
                    sql=f"SELECT {i}",
                    status="succeeded",
                    duration_ms=1.0,
                    rows=1,
                )
            )
        recent = await h.recent(limit=10)
        # Bounded at max_entries=3
        assert len(recent) == 3
        # Most recent first
        assert recent[0].query_id == "q4"
    finally:
        await h.close()


@pytest.mark.asyncio
async def test_recent_skips_rows_with_corrupt_timestamp(tmp_path: Path) -> None:
    h = QueryHistory(tmp_path / "h.db", max_entries=10)
    await h.open()
    try:
        await h.add(
            HistoryEntry(
                query_id="ok",
                connection_label="sqlite:///:memory:",
                sql="SELECT 1",
                status="succeeded",
            )
        )
        # Corrupt the stored timestamp directly.
        conn = h._require()
        await conn.execute("UPDATE history SET started_at='not-a-date' WHERE query_id='ok'")
        await conn.commit()
        # A bad row is skipped rather than aborting the whole fetch.
        assert await h.recent(limit=10) == []
    finally:
        await h.close()
