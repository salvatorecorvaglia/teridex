from __future__ import annotations

import asyncio

import pytest

from teridex_core.events import EventBus
from teridex_core.protocols.plugin import PluginManifest
from teridex_plugins.api import Command, hook
from teridex_plugins.context import PluginContext
from teridex_plugins.loader import PluginLoader
from teridex_plugins.registry import PluginRegistry


class _SamplePlugin:
    manifest = PluginManifest(id="sample", name="Sample", version="1.0.0")

    def __init__(self) -> None:
        self.loaded = False

    def on_load(self, ctx: PluginContext) -> None:
        async def _noop(ctx: PluginContext) -> None:  # noqa: ARG001
            return

        ctx.register_command(
            Command(id="sample.hello", title="Hello", handler=_noop)
        )
        self.loaded = True

    def on_unload(self, ctx: PluginContext) -> None:  # noqa: ARG001
        self.loaded = False


@pytest.mark.asyncio
async def test_loader_registers_plugin_and_command() -> None:
    bus = EventBus()
    registry = PluginRegistry()
    loader = PluginLoader(registry, bus)
    plugin = _SamplePlugin()
    loader.load_instance(plugin)
    assert plugin.loaded
    cmds = registry.all_commands()
    assert any(c.id == "sample.hello" for c in cmds)
    loader.unload("sample")
    assert not plugin.loaded
    # let publish drain
    for _ in range(5):
        await asyncio.sleep(0)
    await bus.close()


def test_hook_decorator_marks_function() -> None:
    @hook("query.before_execute")
    async def my_hook(_ctx: object) -> None:
        return

    from teridex_plugins.api import hook_event, is_hook

    assert is_hook(my_hook)
    assert hook_event(my_hook) == "query.before_execute"
