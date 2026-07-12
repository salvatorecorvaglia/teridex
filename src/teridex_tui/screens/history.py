"""Query history modal — pick a past query to load into the active tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Key

    from teridex_engine.history import HistoryEntry


class HistoryModal(ModalScreen["HistoryEntry | None"]):
    """Modal listing recent queries. Returns the selected entry, or ``None``."""

    def __init__(self, entries: list[HistoryEntry]) -> None:
        super().__init__()
        self._entries = entries

    def compose(self) -> ComposeResult:
        with Vertical(id="HistoryModal"):
            yield Static("[b]Query history[/]\n", id="history-title")
            yield ListView(id="history-list")
            yield Static("\n[dim](enter to load · escape to cancel)[/]", id="history-hint")

    def on_mount(self) -> None:
        lst = self.query_one("#history-list", ListView)
        if not self._entries:
            lst.append(ListItem(Static("[dim]no history yet[/]"), id="history-empty"))
            lst.focus()
            return
        for i, entry in enumerate(self._entries):
            preview_lines = entry.sql.strip().splitlines()
            preview = preview_lines[0] if preview_lines else ""
            if len(preview) > 80:
                preview = preview[:77] + "…"
            status_style = {
                "succeeded": "green",
                "failed": "red",
                "cancelled": "yellow",
            }.get(entry.status, "white")
            label = (
                f"[{status_style}]●[/] [bold]{preview}[/]\n"
                f"   [dim]{entry.connection_label}  ·  "
                f"{entry.duration_ms or 0:.1f} ms  ·  "
                f"{entry.rows or 0} rows[/]"
            )
            lst.append(ListItem(Static(label), id=f"history-{i}"))
        lst.focus()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            lst = self.query_one("#history-list", ListView)
            if lst.has_focus:
                return
            self._submit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._submit()

    def _submit(self) -> None:
        lst = self.query_one("#history-list", ListView)
        item = lst.highlighted_child
        if item is None or item.id is None or item.id == "history-empty":
            self.dismiss(None)
            return
        try:
            idx = int(item.id.removeprefix("history-"))
        except ValueError:
            self.dismiss(None)
            return
        if not 0 <= idx < len(self._entries):
            self.dismiss(None)
            return
        self.dismiss(self._entries[idx])
