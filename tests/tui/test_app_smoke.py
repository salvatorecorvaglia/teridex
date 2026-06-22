"""Smoke test: app boots, mounts, and can be torn down."""

from __future__ import annotations

from typing import Any

import pytest

textual = pytest.importorskip("textual")

from textual.widgets import ListView, Static  # noqa: E402

from teridex_core.config import TeridexConfig, UIConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_core.protocols.plugin import PluginManifest  # noqa: E402
from teridex_plugins.api import Command  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402
from teridex_tui.screens.command_palette import CommandPaletteScreen  # noqa: E402


@pytest.mark.asyncio
async def test_app_boots_in_memory_sqlite() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        # Give startup tasks a chance to settle.
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.state.adapter is not None
        assert app.state.adapter.connected  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_run_query_rejects_reentry_while_in_flight() -> None:
    # Regression: a second run while one is in flight must not clobber the
    # current run handle — it should be rejected up front.
    app = TeridexApp(config=TeridexConfig())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._query_in_flight = True
        await app.action_run_query()
        assert "already running" in app._status().message


@pytest.mark.asyncio
async def test_run_query_empty_sql_gives_feedback() -> None:
    # Running with an empty editor must not silently no-op.
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await app.action_run_query()
        assert "nothing to run" in app._status().message


@pytest.mark.asyncio
async def test_closing_last_tab_keeps_an_editor() -> None:
    # Closing every tab must leave a usable editor behind.
    app = TeridexApp(config=TeridexConfig())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_close_tab()
        await pilot.pause()
        assert app._tabs().current_editor is not None


@pytest.mark.asyncio
async def test_focus_editor_actions_move_cursor() -> None:
    app = TeridexApp(config=TeridexConfig())
    async with app.run_test() as pilot:
        await pilot.pause()
        editor = app._tabs().current_editor
        assert editor is not None
        editor.text = "line1\nline2\nline3"
        await app.action_focus_editor_bottom()
        assert editor.cursor_location == editor.document.end
        await app.action_focus_editor_top()
        assert editor.cursor_location == (0, 0)


@pytest.mark.asyncio
async def test_teardown_closes_connection() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        adapter = app.state.adapter
        assert adapter is not None
        assert adapter.connected  # type: ignore[attr-defined]
    # on_unmount must have torn the connection down.
    assert adapter.connected is False  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_command_palette_invokes_with_correct_plugin_context() -> None:
    app = TeridexApp(config=TeridexConfig())
    resolved_context = None

    class CustomCommandPlugin:
        manifest = PluginManifest(id="custom_cmd_plugin", name="CustomCmd", version="1.0.0")

        def on_load(self, ctx: Any) -> None:
            async def _handler(c: Any) -> None:
                nonlocal resolved_context
                resolved_context = c

            ctx.register_command(Command(id="custom.cmd", title="Run Custom", handler=_handler))

        def on_unload(self, ctx: Any) -> None:
            pass

    async with app.run_test() as pilot:
        await pilot.pause()
        app._loader.load_instance(CustomCommandPlugin())

        # Trigger command palette
        await app.action_command_palette()
        await pilot.pause()

        # Find the command screen and pick our command
        screen = app.screen
        assert isinstance(screen, CommandPaletteScreen)

        lst = screen.query_one("#palette-list", ListView)
        for i, child in enumerate(lst.children):
            cmd = getattr(child, "cmd", None)
            if cmd is not None and cmd.id == "custom.cmd":
                lst.index = i
                break
        else:
            pytest.fail("Custom command option not found in command palette")

        # Press enter to pick the highlighted command
        await pilot.press("enter")
        await pilot.pause()

        # Check if resolved context matches the plugin context
        assert resolved_context is not None
        assert resolved_context.plugin_id == "custom_cmd_plugin"


@pytest.mark.asyncio
async def test_action_bar_unlimited_limit_label() -> None:
    config = TeridexConfig(ui=UIConfig(max_display_rows=0))
    app = TeridexApp(config=config)
    async with app.run_test() as pilot:
        await pilot.pause()
        limit_label = app.query_one("#limit-label", Static)
        assert "Limit Unlimited" in str(limit_label.render())
