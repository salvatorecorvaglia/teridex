"""Tests for ResultsTable empty-state, loading reset, copy, and export paths."""

from __future__ import annotations

import csv

import pytest

textual = pytest.importorskip("textual")

from teridex_core.config import TeridexConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402


@pytest.mark.asyncio
async def test_query_with_rows_sets_count_subtitle(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        editor = app._tabs().current_editor
        assert editor is not None
        editor.text = "SELECT 1 AS a UNION ALL SELECT 2"
        await app.action_run_query()
        await pilot.pause()
        results = app._results()
        assert results.loading is False
        assert results.row_count == 2
        assert results.border_subtitle == "2 rows"


@pytest.mark.asyncio
async def test_query_with_no_rows_sets_empty_subtitle() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        editor = app._tabs().current_editor
        assert editor is not None
        editor.text = "SELECT 1 WHERE 0"
        await app.action_run_query()
        await pilot.pause()
        results = app._results()
        assert results.loading is False
        assert results.row_count == 0
        assert results.border_subtitle == "no rows returned"


@pytest.mark.asyncio
async def test_export_csv_writes_rows(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", str(tmp_path))
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        editor = app._tabs().current_editor
        assert editor is not None
        editor.text = "SELECT 1 AS a, 'hi' AS b UNION ALL SELECT 2, 'bye'"
        await app.action_run_query()
        await pilot.pause()
        await app.action_export_csv()
        exports = list((tmp_path / ".teridex" / "exports").glob("export-*.csv"))
        assert len(exports) == 1
        with exports[0].open() as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["a", "b"]
        assert rows[1:] == [["1", "hi"], ["2", "bye"]]


@pytest.mark.asyncio
async def test_query_with_duplicate_columns() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        editor = app._tabs().current_editor
        assert editor is not None
        editor.text = "SELECT 1 AS a, 2 AS a"
        await app.action_run_query()
        await pilot.pause()
        results = app._results()
        assert results.loading is False
        assert results.row_count == 1
        cols = list(results.columns.values())
        assert len(cols) == 2
        assert str(cols[0].label) == "a"
        assert str(cols[1].label) == "a"
