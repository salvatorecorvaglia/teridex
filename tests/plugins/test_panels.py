"""Plugin panels actually mount into the TUI."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from typing import TYPE_CHECKING  # noqa: E402

from textual.widgets import Static  # noqa: E402

from teridex_core.config import TeridexConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_core.protocols.plugin import PluginManifest  # noqa: E402
from teridex_plugins.api import Panel  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402

if TYPE_CHECKING:
    from teridex_plugins.context import PluginContext
    from teridex_plugins.loader import PluginLoader

_TEXT = "★ plugin-rail-ok"


class _RailPlugin:
    manifest = PluginManifest(id="acme.rail", name="Rail")

    def on_load(self, ctx: PluginContext) -> None:
        def _factory(_c: PluginContext) -> Static:
            return Static(_TEXT, id="acme-rail-text")

        ctx.register_panel(
            Panel(id="acme.rail.right", title="Acme", placement="right", factory=_factory)
        )

    def on_unload(self, ctx: PluginContext) -> None:
        pass


@pytest.mark.asyncio
async def test_no_rails_when_no_plugins() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        # Rails are mounted only when at least one panel exists.
        from textual.css.query import NoMatches  # noqa: PLC0415

        for selector in ("#right-rail", "#bottom-rail"):
            with pytest.raises(NoMatches):
                app.query_one(selector)
        grid = app.query_one("#main-grid")
        assert not grid.has_class("with-right")
        assert not grid.has_class("with-bottom")


@pytest.mark.asyncio
async def test_right_rail_panel_mounts() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        # Manually inject our plugin via the loader stored on the app.
        # The app loads entry-point plugins in ``on_mount``; we inject *after*
        # mount and then re-mount the panel ourselves to verify the seam.
        await pilot.pause()
        await app.workers.wait_for_complete()

        loader: PluginLoader = app._loader  # type: ignore[attr-defined]
        loader.load_instance(_RailPlugin())
        await app._mount_plugin_panels()  # type: ignore[attr-defined]
        await pilot.pause()
        # Look the static widget up by id.
        widget = app.query_one("#acme-rail-text", Static)
        assert _TEXT in str(widget.render())
        # The grid grew its layout to include the right rail.
        grid = app.query_one("#main-grid")
        assert grid.has_class("with-right")
