"""Unit tests for standalone TUI widgets (ActionBar, StatusBar)."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from rich.cells import cell_len  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import Static  # noqa: E402

from teridex_tui.keymaps import key_label  # noqa: E402
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
    # ``render`` returns Textual ``Content``; ``.plain`` is what the user reads,
    # which is a better thing to assert than the markup that produced it.
    bar = StatusBar()
    out = bar.render().plain
    assert "Disconnected." in out
    assert "Quit" in out


def test_status_bar_render_connected() -> None:
    bar = StatusBar()
    bar.connection = "sqlite:///db"
    assert "Database Connected." in bar.render().plain


def test_status_bar_message_takes_precedence() -> None:
    bar = StatusBar()
    bar.connection = "sqlite:///db"
    bar.message = "running…"
    out = bar.render().plain
    assert "running…" in out
    assert "Database Connected." not in out


def test_status_bar_vim_mode_indicator() -> None:
    bar = StatusBar()
    bar.mode = "VIM"
    assert "VIM" in bar.render().plain
    bar.mode = "NORMAL"
    assert "NORMAL" not in bar.render().plain


def test_status_bar_truncation_warning() -> None:
    bar = StatusBar()
    bar.truncated = True
    assert "truncated" in bar.render().plain


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
async def test_footer_pads_using_cell_width_not_character_count() -> None:
    """``^↵`` is one character but the padding must reckon in terminal cells.

    Measuring with ``len()`` over-counted the available room, so the status
    line was padded a cell too wide and wrapped on a full-width terminal.
    """

    bar = StatusBar()
    bar.connection = "sqlite:///:memory:"
    async with _Harness(bar).run_test(size=(200, 10)):
        rendered = bar.render().plain
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


# ---- severity is a chip, not a text colour ----
#
# The bar's own background is ``$warning``. Severity carried by text colour is
# unreadable on it: ``$warning`` on ``$warning`` measures 1.00:1 — literally
# invisible — and ``$error`` only 2.2:1. Every "not connected" / "cancelled" /
# "display truncated" message was affected.


@pytest.mark.parametrize(
    ("severity", "expected_style"),
    [
        ("error", "bold $background on $error"),
        ("warning", "bold $background on $warning-darken-3"),
        ("success", "bold $background on $success"),
    ],
)
def test_severity_renders_as_an_inverted_chip(severity: str, expected_style: str) -> None:
    bar = StatusBar()
    bar.notify_status("something happened", severity)
    content = bar.render()
    assert "something happened" in content.plain
    assert expected_style in [span[2] for span in content.spans]


def test_a_message_without_severity_is_not_styled() -> None:
    bar = StatusBar()
    bar.notify_status("refreshing schema…")
    content = bar.render()
    assert "refreshing schema…" in content.plain
    assert not any("on $" in str(span[2]) for span in content.spans)


def test_unknown_severity_falls_back_to_unstyled() -> None:
    bar = StatusBar()
    bar.notify_status("hmm", "catastrophe")
    assert bar.severity == ""


def test_status_bar_never_parses_its_message_as_markup() -> None:
    """A driver message full of brackets must render verbatim.

    ``Content.assemble`` takes the text as data, so nothing here needs escaping
    and an unbalanced tag cannot raise mid-render.
    """
    hostile = "syntax error near [col] [/] [bold]"
    bar = StatusBar()
    bar.notify_status(hostile, "error")
    assert hostile in bar.render().plain
