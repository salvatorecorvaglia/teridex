"""Default keymap. Bindings are ``(key, action, description)`` tuples."""

from __future__ import annotations

DEFAULT_BINDINGS: list[tuple[str, str, str]] = [
    ("ctrl+enter", "run_query", "Run query"),
    ("ctrl+j", "run_query", "Run query"),
    ("ctrl+c", "cancel_query", "Cancel query"),
    ("ctrl+p", "command_palette", "Command palette"),
    ("ctrl+t", "new_tab", "New tab"),
    ("ctrl+w", "close_tab", "Close tab"),
    ("ctrl+r", "refresh_schema", "Refresh schema"),
    ("ctrl+h", "show_history", "Show history"),
    ("ctrl+y", "copy_cell", "Copy cell"),
    ("ctrl+e", "export_csv", "Export CSV"),
    ("question_mark", "help", "Help"),
    ("ctrl+q", "quit", "Quit"),
]
