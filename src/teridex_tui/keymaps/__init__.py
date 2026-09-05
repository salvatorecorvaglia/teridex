"""Keymap presets."""

from teridex_tui.keymaps._labels import key_label
from teridex_tui.keymaps.default import ACTION_TO_KEY, DEFAULT_BINDINGS
from teridex_tui.keymaps.vim import VIM_ACTION_TO_KEY, VIM_BINDINGS

__all__ = [
    "ACTION_TO_KEY",
    "DEFAULT_BINDINGS",
    "VIM_ACTION_TO_KEY",
    "VIM_BINDINGS",
    "key_label",
]
