"""Main screen — composes sidebar, editor, results, status, and plugin rails."""

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
            # ``#right-rail`` and ``#bottom-rail`` are populated dynamically by
            # the app from registered plugin panels; we yield empty containers
            # so the grid keeps its structure even with no plugins loaded.
            yield Vertical(id="right-rail")
            yield Vertical(id="bottom-rail")
            yield StatusBar()
