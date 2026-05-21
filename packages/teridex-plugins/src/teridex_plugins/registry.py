"""Runtime registry of loaded plugins, commands, and panels."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from teridex_core.errors import PluginError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from teridex_core.protocols.plugin import PluginManifest
    from teridex_plugins.api import Command, Panel


class PluginRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, PluginManifest] = {}
        self._commands_by_plugin: dict[str, list[Command]] = defaultdict(list)
        self._panels_by_plugin: dict[str, list[Panel]] = defaultdict(list)

    def add_plugin(self, manifest: PluginManifest) -> None:
        if manifest.id in self._manifests:
            raise PluginError(
                f"plugin id collision: {manifest.id!r} already registered",
                context={"plugin_id": manifest.id},
            )
        self._manifests[manifest.id] = manifest

    def remove_plugin(self, plugin_id: str) -> None:
        self._manifests.pop(plugin_id, None)
        self._commands_by_plugin.pop(plugin_id, None)
        self._panels_by_plugin.pop(plugin_id, None)

    def add_command(self, plugin_id: str, command: Command) -> None:
        self._commands_by_plugin[plugin_id].append(command)

    def add_panel(self, plugin_id: str, panel: Panel) -> None:
        self._panels_by_plugin[plugin_id].append(panel)

    def manifests(self) -> Iterable[PluginManifest]:
        return self._manifests.values()

    def all_commands(self) -> list[Command]:
        return [cmd for cmds in self._commands_by_plugin.values() for cmd in cmds]

    def all_panels(self) -> list[Panel]:
        return [p for panels in self._panels_by_plugin.values() for p in panels]
