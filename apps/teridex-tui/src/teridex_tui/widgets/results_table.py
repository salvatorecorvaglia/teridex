"""Virtualized results viewer."""

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
        self._initialized = False
        self._column_names: list[str] = []
        self._row_count = 0

    def reset(self) -> None:
        self.clear(columns=True)
        self._initialized = False
        self._column_names = []
        self._row_count = 0
        self.border_subtitle = None

    def feed(self, batch: ResultBatch) -> None:
        if not self._initialized and batch.columns:
            self._column_names = [c.name for c in batch.columns]
            for col in batch.columns:
                self.add_column(col.name, key=col.name)
            self._initialized = True
        if batch.rows:
            self.add_rows(tuple("" if v is None else str(v) for v in row) for row in batch.rows)
            self._row_count += len(batch.rows)

    def mark_done(self) -> None:
        """Show a clear empty-state on the table border when no rows arrived."""
        if not self._initialized or self._row_count == 0:
            self.border_subtitle = "no rows returned"
        else:
            self.border_subtitle = f"{self._row_count} row{'s' if self._row_count != 1 else ''}"

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
