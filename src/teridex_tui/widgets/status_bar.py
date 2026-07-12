"""Yellow footer bar showing keyboard shortcuts.

Layout:  ^q Quit  f1 Help  ^↵ Run Query  ^r Refresh  ...  Database Connected.
"""

from __future__ import annotations

import re

from textual.reactive import reactive
from textual.widgets import Static
from rich.text import Text

# Keybinding labels displayed in the footer (key_label, description).
# Keep these concise — screen width is limited.
_FOOTER_BINDINGS: list[tuple[str, str]] = [
    ("^q", "Quit"),
    ("?", "Help"),
    ("^h", "History"),
    ("^↵", "Run Query"),
    ("^r", "Refresh"),
    ("^t", "New Tab"),
    ("^w", "Close Tab"),
    ("^y", "Copy"),
    ("^e", "Export"),
    ("^p", "Palette"),
]


class StatusBar(Static):
    DEFAULT_CSS = ""

    connection: reactive[str] = reactive("disconnected")
    mode: reactive[str] = reactive("NORMAL")
    message: reactive[str] = reactive("")
    rows: reactive[int] = reactive(0)
    duration_ms: reactive[float] = reactive(0.0)
    has_run: reactive[bool] = reactive(False)
    truncated: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__(id="status-bar")

    def validate_message(self, value: str | None) -> str:
        return value or ""

    def render(self) -> str:
        # Left: keybinding hints, with the active keymap when it isn't the
        # default — vim bindings are otherwise invisible to the user.
        shortcuts = "  ".join(f"[bold]{key}[/] {desc}" for key, desc in _FOOTER_BINDINGS)
        if self.mode and self.mode != "NORMAL":
            shortcuts = f"[bold reverse] {self.mode} [/]  {shortcuts}"

        # Right: connection / message status
        if self.message:
            status = self.message
        elif self.connection and self.connection != "disconnected":
            status = "Database Connected."
        else:
            status = "Disconnected."

        if self.truncated:
            status = f"[yellow]display truncated[/]  ·  {status}"

        raw_shortcuts = Text.from_markup(shortcuts).plain
        raw_status = Text.from_markup(status).plain
        width = self.size.width or 80
        available = width - 2  # account for padding
        padding_len = available - len(raw_shortcuts) - len(raw_status)
        if padding_len > 0:
            return f"{shortcuts}{' ' * padding_len}{status}"
        return f"{shortcuts}  {status}"
