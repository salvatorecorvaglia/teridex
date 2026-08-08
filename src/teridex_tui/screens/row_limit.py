"""Row limit screen — prompt the user for a new row display cap."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.widgets import Button, Input, Static

from teridex_tui.screens._base import BaseModal

if TYPE_CHECKING:
    from textual.app import ComposeResult


class RowLimitModal(BaseModal[int]):
    """Modal prompting for a results display row limit.

    Returns the integer limit (0 for unlimited) on submit, or None on cancel.
    """

    def __init__(self, current_limit: int) -> None:
        super().__init__()
        self._current_limit = current_limit

    def compose(self) -> ComposeResult:
        with Vertical(id="RowLimitModal"):
            yield Static("[bold]Set Row Display Limit[/]\n", id="limit-title")
            yield Input(
                value=str(self._current_limit),
                placeholder="Enter limit (0 for unlimited)",
                id="limit-input",
            )
            yield Button("Set Limit", id="limit-submit-btn", variant="primary")
            yield Static(
                "\n[dim](enter to save · escape to cancel)[/]",
                id="limit-hint",
            )

    def on_mount(self) -> None:
        inp = self.query_one("#limit-input", Input)
        inp.focus()
        inp.select_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "limit-submit-btn":
            self.submit()

    def submit(self) -> None:
        value_str = self.query_one("#limit-input", Input).value.strip()
        try:
            val = int(value_str)
            if val < 0:
                raise ValueError()
        except ValueError:
            return
        self.dismiss(val)
