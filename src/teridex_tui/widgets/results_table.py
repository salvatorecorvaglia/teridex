"""Results viewer backed by a Textual ``DataTable``.

The grid holds at most :attr:`max_rows` rows (``0`` = unlimited); excess rows
from a large stream are dropped and flagged so a truncated view is never
mistaken for the full result set.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from textual.widgets import DataTable
from textual.widgets.data_table import CellDoesNotExist

from teridex_core.export import csv_safe_row

if TYPE_CHECKING:
    from pathlib import Path

    from teridex_core.models.result import ResultBatch


# Rows inserted between yields to the event loop.
_CHUNK_ROWS = 1000


def _format_rows(rows: list[tuple[Any, ...]]) -> list[tuple[str, ...]]:
    """Render raw values for display.

    Cells are interpreted as Rich markup, so anything a database can return —
    JSON arrays, regexes, Python reprs — has to be escaped. A bare ``[/]``
    would otherwise raise ``MarkupError`` and take the render down with it.
    """
    return [tuple("[dim]NULL[/]" if v is None else escape(str(v)) for v in row) for row in rows]


class ResultsTable(DataTable[str]):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__(id="results-table", zebra_stripes=True, header_height=1)
        self.cursor_type = "cell"
        self.max_rows = 0  # 0 = unlimited; set from cfg.ui.max_display_rows
        self._initialized = False
        self._column_names: list[str] = []
        self._rows: list[tuple[Any, ...]] = []
        self._row_count = 0
        self._truncated = False

    def reset(self) -> None:
        self.clear(columns=True)
        self._initialized = False
        self._column_names = []
        self._rows = []
        self._row_count = 0
        self._truncated = False
        self.border_subtitle = None

    async def feed(self, batch: ResultBatch) -> None:
        if not self._initialized and batch.columns:
            self._column_names = [c.name for c in batch.columns]
            for i, col in enumerate(batch.columns):
                self.add_column(escape(col.name), key=str(i))
            self._initialized = True
        if not batch.rows:
            return
        rows = batch.rows
        if self.max_rows:
            if self._row_count >= self.max_rows:
                self._truncated = True
                return
            remaining = self.max_rows - self._row_count
            if len(rows) > remaining:
                rows = rows[:remaining]
                self._truncated = True

        # Raw values are kept alongside the grid's own (escaped, Rich-rendered)
        # copy because copy-cell and CSV export must reproduce what the
        # database returned, not what was displayed.
        self._rows.extend(rows)

        # Format and insert in chunks rather than materializing the whole
        # batch first: peak memory stays at one chunk, and the await between
        # chunks keeps the UI responsive while a large batch lands.
        for start in range(0, len(rows), _CHUNK_ROWS):
            chunk = rows[start : start + _CHUNK_ROWS]
            self.add_rows(_format_rows(chunk))
            self._row_count += len(chunk)
            if start + _CHUNK_ROWS < len(rows):
                await asyncio.sleep(0)

    def mark_done(self, *, cancelled: bool = False) -> None:
        """Summarize the run on the table border.

        ``cancelled`` flags the result set as incomplete so a partial result
        is not mistaken for the full output.
        """
        if not self._initialized or self._row_count == 0:
            self.border_subtitle = "cancelled — no rows" if cancelled else "no rows returned"
            return
        n = self._row_count
        parts = [f"{n} row{'s' if n != 1 else ''}"]
        if self._truncated:
            parts.append(f"display capped at {self.max_rows}")
        if cancelled:
            parts.append("cancelled (partial)")
        self.border_subtitle = " · ".join(parts)

    @property
    def truncated(self) -> bool:
        """True when the display capped the result set below its real size."""
        return self._truncated

    def current_cell_text(self) -> str | None:
        """Raw text of the cell under the cursor — never the escaped rendering."""
        if not self._initialized or self.row_count == 0:
            return None
        row, column = self.cursor_coordinate
        if 0 <= row < len(self._rows):
            source = self._rows[row]
            if 0 <= column < len(source):
                val = source[column]
                return "" if val is None else str(val)
        try:
            rendered = self.get_cell_at(self.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return "" if rendered is None else str(rendered)

    async def export_csv(self, path: Path) -> int:
        columns = list(self._column_names)
        data = list(self._rows)

        def _write(p: Path, cols: list[str], data_rows: list[tuple[Any, ...]]) -> None:
            p.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(Exception):
                p.parent.chmod(0o700)
            with p.open("w", newline="", encoding="utf-8") as f:
                with contextlib.suppress(Exception):
                    p.chmod(0o600)
                w = csv.writer(f)
                w.writerow(cols)
                # Defused so a value like ``=1+1`` is text in the spreadsheet
                # rather than a formula it evaluates on open.
                w.writerows(csv_safe_row(r) for r in data_rows)

        await asyncio.to_thread(_write, path, columns, data)
        return len(data)
