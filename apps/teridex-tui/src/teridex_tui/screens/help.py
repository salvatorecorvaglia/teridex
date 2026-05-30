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
        bindings = list(self.app.BINDINGS)
        cfg = getattr(self.app, "cfg", None)
        if cfg is not None and getattr(cfg.ui, "keymap", "default") == "vim":
            from teridex_tui.keymaps import VIM_BINDINGS  # noqa: PLC0415

            for vimb in VIM_BINDINGS:
                if not any(
                    (isinstance(existing, Binding) and existing.key == vimb[0])
                    or (isinstance(existing, tuple) and existing[0] == vimb[0])
                    for existing in bindings
                ):
                    bindings.append(vimb)

        for item in bindings:
            if isinstance(item, Binding):
                rows.append((item.key, item.description or item.action))
            elif isinstance(item, tuple) and len(item) == 3:
                key, action, desc = item
                rows.append((key, desc or action))
            elif isinstance(item, tuple) and len(item) == 2:
                key, action = item
                rows.append((key, action))
        if not rows:
            return "[dim]no bindings registered[/]"
        width = max(len(k) for (k, _) in rows)
        return "\n".join(f"  [bold cyan]{key.ljust(width)}[/]  {desc}" for (key, desc) in rows)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
