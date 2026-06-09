"""Query history persisted in a local SQLite store under ``~/.teridex``."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
from pydantic import BaseModel, ConfigDict, Field

from teridex_core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL,
    connection_label TEXT NOT NULL,
    sql TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL,
    rows INTEGER,
    error TEXT,
    started_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_started ON history(started_at DESC);
"""


class HistoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    query_id: str
    connection_label: str
    sql: str
    status: str
    duration_ms: float | None = None
    rows: int | None = None
    error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QueryHistory:
    """Append-only history with a bounded retention window."""

    def __init__(self, path: Path | None = None, *, max_entries: int = 1000) -> None:
        self._path = path or (Path.home() / ".teridex" / "history.db")
        self._max = max_entries
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(Exception):
            self._path.parent.chmod(0o700)
        if not self._path.exists():
            with contextlib.suppress(Exception):
                self._path.touch()
        with contextlib.suppress(Exception):
            self._path.chmod(0o600)
        self._conn = await aiosqlite.connect(self._path)
        with contextlib.suppress(aiosqlite.Error):
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("QueryHistory not opened")
        return self._conn

    async def add(self, entry: HistoryEntry) -> int:
        conn = self._require()
        cur = await conn.execute(
            "INSERT INTO history "
            "(query_id, connection_label, sql, status, duration_ms, rows, error, started_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                entry.query_id,
                entry.connection_label,
                entry.sql,
                entry.status,
                entry.duration_ms,
                entry.rows,
                entry.error,
                entry.started_at.isoformat(),
            ),
        )
        rowid = cur.lastrowid or 0
        await cur.close()
        await self._trim()
        await conn.commit()
        return rowid

    async def recent(self, limit: int = 50) -> list[HistoryEntry]:
        conn = self._require()
        async with conn.execute(
            "SELECT id, query_id, connection_label, sql, status, duration_ms,"
            " rows, error, started_at FROM history ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        entries: list[HistoryEntry] = []
        for r in rows:
            try:
                started_at = datetime.fromisoformat(r[8])
            except (ValueError, TypeError):
                # Corrupt or legacy timestamp: skip this row rather than abort
                # the whole fetch.
                logger.warning("history_row_skipped", history_id=r[0], started_at=r[8])
                continue
            entries.append(
                HistoryEntry(
                    id=r[0],
                    query_id=r[1],
                    connection_label=r[2],
                    sql=r[3],
                    status=r[4],
                    duration_ms=r[5],
                    rows=r[6],
                    error=r[7],
                    started_at=started_at,
                )
            )
        return entries

    async def _trim(self) -> None:
        conn = self._require()
        await conn.execute(
            "DELETE FROM history WHERE id NOT IN ("
            "  SELECT id FROM history ORDER BY started_at DESC LIMIT ?"
            ")",
            (self._max,),
        )
