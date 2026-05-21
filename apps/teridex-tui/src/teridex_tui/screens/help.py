"""Help modal — lists the currently active keybindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Key


class HelpModal(ModalScreen[None]):
    """Press ``?`` to view, ``escape`` to dismiss."""

    def compose(self) -> ComposeResult:
        with Vertical(id="HelpModal"):
            yield Static("[b]Teridex — Keybindings[/]\n", id="help-title")
            yield Static(self._render_bindings(), id="help-bindings")
            yield Static("\n[dim](press escape to close)[/]", id="help-hint")

    def _render_bindings(self) -> str:
        rows: list[tuple[str, str]] = []
        for b in self.app.BINDINGS:
            if isinstance(b, Binding):
                rows.append((b.key, b.description or b.action))
            elif isinstance(b, tuple) and len(b) == 3:
                key, action, desc = b
                rows.append((key, desc or action))
            elif isinstance(b, tuple) and len(b) == 2:
                key, action = b
                rows.append((key, action))
        if not rows:
            return "[dim]no bindings registered[/]"
        width = max(len(k) for (k, _) in rows)
        return "\n".join(f"  [bold cyan]{key.ljust(width)}[/]  {desc}" for (key, desc) in rows)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
