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
    # Not ``ctrl+h``: terminals send that for Backspace (it is ASCII BS), so an
    # app-level binding there fires on an ordinary edit keystroke.
    ("ctrl+g", "show_history", "Show history"),
    ("ctrl+y", "copy_cell", "Copy cell"),
    ("ctrl+e", "export_csv", "Export CSV"),
    ("question_mark", "help", "Help"),
    ("ctrl+q", "quit", "Quit"),
]

# One key per action, so callers (e.g. ``BUILTIN_COMMANDS``) can look up a
# binding's display string instead of hand-duplicating it — a duplicated
# literal is what let the palette's hint strings drift from the real keymap.
# ``setdefault`` keeps the *first* key listed above for an action (e.g.
# ``run_query``'s primary binding is ``ctrl+enter``, not the ``ctrl+j`` alias).
ACTION_TO_KEY: dict[str, str] = {}
for _key, _action, _desc in DEFAULT_BINDINGS:
    ACTION_TO_KEY.setdefault(_action, _key)
del _key, _action, _desc
