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
async def test_right_rail_panel_mounts() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        # Manually inject our plugin via the loader stored on the app.
        # The app loads entry-point plugins in ``on_mount``; we inject *after*
        # mount and then re-mount the panel ourselves to verify the seam.
        await pilot.pause()

        loader: PluginLoader = app._loader  # type: ignore[attr-defined]
        loader.load_instance(_RailPlugin())
        await app._mount_plugin_panels()  # type: ignore[attr-defined]
        await pilot.pause()
        # Look the static widget up by id.
        widget = app.query_one("#acme-rail-text", Static)
        assert _TEXT in str(widget.render())
        rail = app.query_one("#right-rail")
        assert rail.has_class("has-panels")
