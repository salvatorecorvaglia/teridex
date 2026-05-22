"""Unit tests for standalone TUI widgets (ActionBar, StatusBar)."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import Static  # noqa: E402

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
