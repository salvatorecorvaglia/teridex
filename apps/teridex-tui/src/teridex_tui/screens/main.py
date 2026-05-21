"""Main screen — composes sidebar, editor, results, status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Static

from teridex_tui.widgets import QueryTabs, ResultsTable, SchemaTree, StatusBar

if TYPE_CHECKING:
    from textual.app import ComposeResult


class MainScreen(Screen[None]):
    DEFAULT_CSS = ""

    def compose(self) -> ComposeResult:
        with Container(id="main-grid"):
            with Vertical(id="sidebar"):
                yield Static("[b]Schema[/b]")
                yield SchemaTree()
            with Vertical(id="workspace"):
                yield QueryTabs()
                with Container(id="results-area"):
                    yield ResultsTable()
            yield StatusBar()
