"""Virtualized results viewer."""

from __future__ import annotations

from textual.widgets import DataTable

from teridex_core.models.result import ResultBatch


class ResultsTable(DataTable[str]):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__(id="results-table", zebra_stripes=True, header_height=1)
        self.cursor_type = "row"
        self._initialized = False

    def reset(self) -> None:
        self.clear(columns=True)
        self._initialized = False

    def feed(self, batch: ResultBatch) -> None:
        if not self._initialized and batch.columns:
            for col in batch.columns:
                self.add_column(col.name, key=col.name)
            self._initialized = True
        if batch.rows:
            self.add_rows(
                tuple("" if v is None else str(v) for v in row) for row in batch.rows
            )
