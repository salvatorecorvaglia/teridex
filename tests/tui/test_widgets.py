"""Unit tests for standalone TUI widgets (ActionBar, StatusBar)."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from rich.cells import cell_len  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import Static  # noqa: E402

from teridex_tui.keymaps import ACTION_TO_KEY, key_label  # noqa: E402
from teridex_tui.widgets.action_bar import ActionBar  # noqa: E402
from teridex_tui.widgets.status_bar import StatusBar  # noqa: E402


class _Harness(App[None]):
    def __init__(self, widget: ActionBar | StatusBar) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


# ---- StatusBar ---------------------------------------------------------


def test_status_bar_render_disconnected() -> None:
    bar = StatusBar()
    out = bar.render()
    assert "Disconnected." in out
    assert "Quit" in out


def test_status_bar_render_connected() -> None:
    bar = StatusBar()
    bar.connection = "sqlite:///db"
    assert "Database Connected." in bar.render()


def test_status_bar_message_takes_precedence() -> None:
    bar = StatusBar()
    bar.connection = "sqlite:///db"
    bar.message = "running…"
    out = bar.render()
    assert "running…" in out
    assert "Database Connected." not in out


def test_status_bar_vim_mode_indicator() -> None:
    bar = StatusBar()
    bar.mode = "VIM"
    assert "VIM" in bar.render()
    bar.mode = "NORMAL"
    assert "NORMAL" not in bar.render()


def test_status_bar_truncation_warning() -> None:
    bar = StatusBar()
    bar.truncated = True
    assert "truncated" in bar.render()


# ---- ActionBar ---------------------------------------------------------


@pytest.mark.asyncio
async def test_action_bar_watch_limit_updates_label() -> None:
    bar = ActionBar()
    async with _Harness(bar).run_test() as pilot:
        bar.limit = 250
        await pilot.pause()
        label = bar.query_one("#limit-label", Static)
        assert "250" in str(label.render())


@pytest.mark.asyncio
async def test_action_bar_watch_tx_mode_updates_label() -> None:
    bar = ActionBar()
    async with _Harness(bar).run_test() as pilot:
        bar.tx_mode = "Manual"
        await pilot.pause()
        label = bar.query_one("#tx-label", Static)
        assert "Manual" in str(label.render())


# ---- footer is derived, not restated ------------------------------------


def test_footer_keys_follow_the_keymap() -> None:
    """The footer must render the keymap's real key, not a hardcoded copy.

    The footer used to hardcode both the key and the label, so moving a binding
    (``show_history`` off ``ctrl+h``, which terminals send for Backspace) left
    the footer advertising a key that no longer did anything.
    """
    out = Text.from_markup(StatusBar().render()).plain

    assert f"{key_label(ACTION_TO_KEY['show_history'])} History" in out
    assert f"{key_label(ACTION_TO_KEY['quit'])} Quit" in out
    assert "^h History" not in out, "footer still advertises the retired Backspace binding"


def test_footer_uses_the_vim_keymap_in_vim_mode() -> None:
    bar = StatusBar()
    bar.mode = "VIM"
    out = Text.from_markup(bar.render()).plain

    assert "gg Top" in out
    assert "G Bottom" in out


@pytest.mark.asyncio
async def test_footer_pads_using_cell_width_not_character_count() -> None:
    """``^↵`` is one character but the padding must reckon in terminal cells.

    Measuring with ``len()`` over-counted the available room, so the status
    line was padded a cell too wide and wrapped on a full-width terminal.
    """

    bar = StatusBar()
    bar.connection = "sqlite:///:memory:"
    async with _Harness(bar).run_test(size=(200, 10)):
        rendered = Text.from_markup(bar.render()).plain
        # Padded to exactly the widget's width less its 1-cell padding a side.
        assert cell_len(rendered) == bar.size.width - 2
        assert "^↵ Run Query" in rendered


def test_key_label_renders_bindings_the_way_users_type_them() -> None:
    assert key_label("ctrl+q") == "^q"
    assert key_label("ctrl+enter") == "^↵"
    assert key_label("question_mark") == "?"
    assert key_label("shift+g") == "G"
    assert key_label("g,g") == "gg"
    assert key_label("colon") == ":"
