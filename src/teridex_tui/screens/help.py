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
            cfg = getattr(self.app, "cfg", None)
            if cfg is not None and getattr(cfg.ui, "keymap", "default") == "vim":
                yield Static(
                    "[yellow]Note: Vim mode applies to global/panel navigation controls "
                    "(e.g., j/k in list views, G/gg in panels). The query editor itself "
                    "remains in standard insert mode.[/]\n",
                    id="help-vim-note",
                )
            yield Static(self._render_bindings(), id="help-bindings")
            yield Static("\n[dim](press escape to close)[/]", id="help-hint")

    def _render_bindings(self) -> str:
        cfg = getattr(self.app, "cfg", None)
        is_vim = cfg is not None and getattr(cfg.ui, "keymap", "default") == "vim"

        # Categorize keys
        global_rows: list[tuple[str, str]] = []
        vim_rows: list[tuple[str, str]] = []

        from teridex_tui.keymaps.default import DEFAULT_BINDINGS  # noqa: PLC0415

        default_keys = {k for k, _, _ in DEFAULT_BINDINGS}

        # Process all bindings from app.BINDINGS first
        for item in self.app.BINDINGS:
            key: str
            desc: str
            if isinstance(item, Binding):
                key = item.key
                desc = item.description or item.action
            elif isinstance(item, tuple) and len(item) == 3:
                key, action, d = item
                desc = d or action
            else:
                key, action = item
                desc = action
            global_rows.append((key, desc))

        if is_vim:
            from teridex_tui.keymaps.vim import VIM_BINDINGS  # noqa: PLC0415

            for vimb in VIM_BINDINGS:
                key, action, d = vimb
                desc = d or action
                if key not in default_keys and not any(k == key for k, _ in vim_rows):
                    vim_rows.append((key, desc))

        lines: list[str] = []
        if global_rows:
            lines.append("[bold yellow]Global Bindings[/]")
            width = max(len(k) for (k, _) in global_rows)
            for key, desc in global_rows:
                lines.append(f"  [bold cyan]{key.ljust(width)}[/]  {desc}")

        if is_vim and vim_rows:
            lines.append("\n[bold yellow]Vim Navigation Bindings[/]")
            width = max(len(k) for (k, _) in vim_rows)
            for key, desc in vim_rows:
                lines.append(f"  [bold cyan]{key.ljust(width)}[/]  {desc}")

        if not lines:
            return "[dim]no bindings registered[/]"
        return "\n".join(lines)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
