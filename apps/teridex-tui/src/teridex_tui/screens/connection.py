"""Connection dialog — prompt the user for a DSN when none is provided."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Key


# Common DSN presets surfaced as clickable shortcuts.
_PRESETS: list[tuple[str, str]] = [
    ("DuckDB (in-memory)", "duckdb:///:memory:"),
    ("SQLite (in-memory)", "sqlite:///:memory:"),
    ("PostgreSQL (local)", "postgres://teridex:teridex@localhost:5432/teridex"),
    ("MySQL (local)", "mysql://teridex:teridex@localhost:3306/teridex"),
]


class ConnectionScreen(ModalScreen[str | None]):
    """Modal prompting for a database DSN.

    Returns the raw DSN string on submit, or ``None`` on escape/cancel.
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="ConnectionModal"):
            yield Static("[b]Connect to Database[/]\n", id="conn-title")
            yield Input(
                placeholder="Enter DSN (e.g. duckdb:///:memory:)",
                id="conn-input",
            )
            with ListView(id="conn-presets"):
                for i, (label, dsn) in enumerate(_PRESETS):
                    yield ListItem(
                        Static(f"[bold]{label}[/]  [dim]{dsn}[/]"),
                        id=f"preset-{i}",
                    )
            yield Button("Connect", id="conn-submit-btn", variant="primary")
            yield Static(
                "\n[dim](tab to select presets · click a preset to populate · "
                "enter to connect · escape to cancel)[/]",
                id="conn-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#conn-input", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._submit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id and event.item.id.startswith("preset-"):
            try:
                idx = int(event.item.id.removeprefix("preset-"))
                dsn = _PRESETS[idx][1]
            except (ValueError, IndexError):
                return
            inp = self.query_one("#conn-input", Input)
            inp.value = dsn
            inp.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "conn-submit-btn":
            self._submit()

    def _submit(self) -> None:
        value = self.query_one("#conn-input", Input).value.strip()
        if not value:
            return
        self.dismiss(value)
