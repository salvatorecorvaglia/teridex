"""Vim-flavored keymap. Editor itself runs in normal-mode style."""

from __future__ import annotations

from teridex_tui.keymaps.default import DEFAULT_BINDINGS

VIM_BINDINGS: list[tuple[str, str, str]] = [
    *DEFAULT_BINDINGS,
    ("colon", "command_palette", "Ex command"),
    ("g,g", "focus_editor_top", "Top of editor"),
    ("shift+g", "focus_editor_bottom", "Bottom of editor"),
]
