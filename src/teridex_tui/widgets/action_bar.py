"""Action bar between Query Editor and Query Results.

Displays transaction mode, row limit, and a Run Query button.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.reactive import reactive
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ActionBar(Static):
    DEFAULT_CSS = ""

    limit: reactive[int] = reactive(500)
    tx_mode: reactive[str] = reactive("Auto")
    connection_status: reactive[str] = reactive("Disconnected.")

    def __init__(self) -> None:
        super().__init__(id="action-bar")

    def compose(self) -> ComposeResult:
        yield Static(f"Tx: {self.tx_mode}", classes="action-label", id="tx-label")
        yield Static(f"Limit {self.limit}", classes="action-label", id="limit-label")
        yield Button("Run Query", id="run-query-btn", variant="primary")

    def watch_limit(self, value: int) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#limit-label", Static).update(f"Limit {value}")

    def watch_tx_mode(self, value: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#tx-label", Static).update(f"Tx: {value}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-query-btn":
            # run_action dispatches by name, so this stays decoupled from the
            # concrete App subclass (App[Any] has no action_run_query attr).
            await self.app.run_action("run_query")
