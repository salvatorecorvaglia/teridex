from __future__ import annotations

from teridex_tui.builtin_commands import BUILTIN_COMMANDS
from teridex_tui.keymaps.default import DEFAULT_BINDINGS


def _expected_key_by_action() -> dict[str, str]:
    expected: dict[str, str] = {}
    for key, action, _desc in DEFAULT_BINDINGS:
        expected.setdefault(action, key)
    return expected


def test_builtin_command_bindings_match_the_default_keymap() -> None:
    """Regression guard: the palette's hint strings must track the real
    keymap instead of a hand-duplicated literal that can silently drift
    from it."""
    expected = _expected_key_by_action()
    for cmd in BUILTIN_COMMANDS:
        action = cmd.id.removeprefix("builtin.")
        if action in expected:
            assert cmd.default_binding == expected[action], cmd.id
        else:
            assert cmd.default_binding is None, cmd.id


def test_every_keybound_action_is_palette_discoverable() -> None:
    palette_actions = {cmd.id.removeprefix("builtin.") for cmd in BUILTIN_COMMANDS}
    bound_actions = {action for _key, action, _desc in DEFAULT_BINDINGS}
    # Opening the palette from within the palette isn't a meaningful entry.
    bound_actions.discard("command_palette")
    missing = bound_actions - palette_actions
    assert not missing, f"actions bound to a key but missing from the command palette: {missing}"
