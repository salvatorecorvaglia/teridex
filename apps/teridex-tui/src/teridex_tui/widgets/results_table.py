"""Results viewer backed by a Textual ``DataTable``.

The grid holds at most :attr:`max_rows` rows (``0`` = unlimited); excess rows
from a large stream are dropped and flagged so a truncated view is never
mistaken for the full result set.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

from textual.widgets import DataTable

if TYPE_CHECKING:
    from pathlib import Path

    from teridex_core.models.result import ResultBatch


class ResultsTable(DataTable[str]):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__(id="results-table", zebra_stripes=True, header_height=1)
        self.cursor_type = "cell"
        self.max_rows = 0  # 0 = unlimited; set from cfg.ui.max_display_rows
        self._initialized = False
        self._column_names: list[str] = []
        self._row_count = 0
        self._truncated = False

    def reset(self) -> None:
        self.clear(columns=True)
        self._initialized = False
        self._column_names = []
        self._row_count = 0
        self._truncated = False
        self.border_subtitle = None

    def feed(self, batch: ResultBatch) -> None:
        if not self._initialized and batch.columns:
            self._column_names = [c.name for c in batch.columns]
            for col in batch.columns:
                self.add_column(col.name, key=col.name)
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
        self.add_rows(tuple("" if v is None else str(v) for v in row) for row in rows)
        self._row_count += len(rows)

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

    def current_cell_text(self) -> str | None:
        if not self._initialized or self.row_count == 0:
            return None
        try:
            val = self.get_cell_at(self.cursor_coordinate)
        except Exception:
            return None
        return "" if val is None else str(val)

    def export_csv(self, path: Path) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self._column_names)
            for i in range(self.row_count):
                w.writerow(self.get_row_at(i))
        return self.row_count
