"""Database content must never be interpreted as Rich markup.

Result cells, schema identifiers and history previews all flow into widgets
that render markup. Values containing square brackets are entirely ordinary
(JSON arrays, regexes, Python reprs), and an unbalanced ``[`` raises
``rich.errors.MarkupError`` mid-render.
"""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from rich.text import Text  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402

from teridex_core.models.result import Column, ResultBatch  # noqa: E402
from teridex_core.models.schema import (  # noqa: E402
    ForeignKey,
    Index,
    SchemaSnapshot,
    Table,
    TableColumn,
)
from teridex_tui.widgets.results_table import ResultsTable  # noqa: E402
from teridex_tui.widgets.schema_tree import SchemaTree  # noqa: E402

_HOSTILE = "[bold]danger[/]"
# A bare closing tag is the crash case: Rich raises MarkupError on it.
_UNBALANCED = "[/]"


class _ResultsHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield ResultsTable()


class _TreeHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield SchemaTree()


@pytest.mark.asyncio
async def test_result_cells_render_markup_literally() -> None:
    app = _ResultsHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(ResultsTable)
        await table.feed(
            ResultBatch(
                columns=[Column(name="payload"), Column(name=_HOSTILE)],
                rows=[(_HOSTILE, _UNBALANCED)],
            )
        )
        # The stored cell keeps the markup escaped...
        rendered = table.get_cell_at((0, 0))
        assert Text.from_markup(str(rendered)).plain == _HOSTILE
        # ...and the unbalanced bracket does not blow up rendering.
        assert Text.from_markup(str(table.get_cell_at((0, 1)))).plain == _UNBALANCED


@pytest.mark.asyncio
async def test_copy_cell_returns_the_raw_value_not_the_escaped_one() -> None:
    app = _ResultsHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(ResultsTable)
        await table.feed(ResultBatch(columns=[Column(name="payload")], rows=[(_HOSTILE,)]))
        table.cursor_coordinate = (0, 0)  # type: ignore[assignment]
        assert table.current_cell_text() == _HOSTILE


@pytest.mark.asyncio
async def test_export_csv_writes_raw_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = _ResultsHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(ResultsTable)
        await table.feed(ResultBatch(columns=[Column(name="payload")], rows=[(_HOSTILE,)]))
        target = tmp_path / "out.csv"
        assert await table.export_csv(target) == 1
        assert _HOSTILE in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_schema_identifiers_render_markup_literally() -> None:
    app = _TreeHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(SchemaTree)
        table = Table(
            name=_HOSTILE,
            schema_name="main",
            columns=[TableColumn(name=_UNBALANCED, type_native="TEXT[]")],
            indexes=[Index(name=_HOSTILE, columns=["a"])],
            foreign_keys=[
                ForeignKey(
                    name="fk",
                    columns=[_HOSTILE],
                    referenced_table=_UNBALANCED,
                    referenced_columns=["id"],
                )
            ],
        )
        tree.populate(
            SchemaSnapshot(connection_id="c", database=_HOSTILE, schemas={"main": [table]})
        )

        labels = [str(tree.root.label)]
        stack = list(tree.root.children)
        while stack:
            node = stack.pop()
            labels.append(str(node.label))
            stack.extend(node.children)
        assert _HOSTILE in labels

        # Filling an object node must not raise on the unbalanced bracket.
        object_node = tree.root.children[0].children[0].children[0]
        tree._fill_object_node(object_node, table)
        column_labels = [
            str(leaf.label) for group in object_node.children for leaf in group.children
        ]
        assert any(_UNBALANCED in label for label in column_labels)
