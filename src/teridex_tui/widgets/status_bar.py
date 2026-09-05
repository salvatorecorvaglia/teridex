"""Yellow footer bar showing keyboard shortcuts.

Layout:  ^q Quit  ? Help  ^↵ Run Query  ^r Refresh  ...  Database Connected.
"""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from teridex_tui.keymaps import ACTION_TO_KEY, VIM_ACTION_TO_KEY, key_label

# Actions surfaced in the footer, in display order, each with the short label
# the footer shows. Only the *label* is written here — the key is resolved from
# the active keymap, because a footer that restates its own keys is a footer
# that drifts from the real bindings the first time one of them moves.
# Labels stay hand-tuned rather than reusing the keymap descriptions: screen
# width is the constraint here, not completeness.
_DEFAULT_FOOTER_ACTIONS: list[tuple[str, str]] = [
    ("quit", "Quit"),
    ("help", "Help"),
    ("show_history", "History"),
    ("run_query", "Run Query"),
    ("refresh_schema", "Refresh"),
    ("new_tab", "New Tab"),
    ("close_tab", "Close Tab"),
    ("copy_cell", "Copy"),
    ("export_csv", "Export"),
    ("command_palette", "Palette"),
]

_VIM_FOOTER_ACTIONS: list[tuple[str, str]] = [
    ("quit", "Quit"),
    ("help", "Help"),
    ("show_history", "History"),
    ("run_query", "Run Query"),
    ("focus_editor_top", "Top"),
    ("focus_editor_bottom", "Bottom"),
    ("new_tab", "New Tab"),
    ("close_tab", "Close Tab"),
    ("copy_cell", "Copy"),
    ("export_csv", "Export"),
    ("command_palette", "Palette"),
]


def _footer_bindings(actions: list[tuple[str, str]], keys: dict[str, str]) -> list[tuple[str, str]]:
    """Resolve ``(action, label)`` pairs against a keymap, skipping unbound ones."""
    return [(key_label(keys[action]), label) for action, label in actions if action in keys]


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
        # Left: keybinding hints, with the active keymap when it isn't default
        bindings = (
            _footer_bindings(_VIM_FOOTER_ACTIONS, VIM_ACTION_TO_KEY)
            if self.mode == "VIM"
            else _footer_bindings(_DEFAULT_FOOTER_ACTIONS, ACTION_TO_KEY)
        )
        shortcuts = "  ".join(f"[bold]{key}[/] {desc}" for key, desc in bindings)
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

        # Measured in terminal cells, not characters: the labels carry glyphs
        # like ``^↵`` whose rendered width is not their ``len()``.
        shortcuts_width = Text.from_markup(shortcuts).cell_len
        status_width = Text.from_markup(status).cell_len
        width = self.size.width or 80
        available = width - 2  # account for padding
        padding_len = available - shortcuts_width - status_width
        if padding_len > 0:
            return f"{shortcuts}{' ' * padding_len}{status}"
        return f"{shortcuts}  {status}"
