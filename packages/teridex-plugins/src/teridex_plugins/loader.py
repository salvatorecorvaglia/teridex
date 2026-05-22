"""Plugin discovery via entry points + manual registration."""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, Any

from teridex_core.errors import PluginError, PluginLoadError
from teridex_core.events import EventBus, PluginLoaded, PluginUnloaded
from teridex_core.logging import get_logger
from teridex_core.protocols.plugin import PluginManifest
from teridex_plugins.context import PluginContext

if TYPE_CHECKING:
    from collections.abc import Iterable

    from teridex_plugins.registry import PluginRegistry

logger = get_logger(__name__)


class PluginLoader:
    """Discovers and instantiates plugins.

    A plugin entry point points at a callable returning an object exposing::

        manifest: PluginManifest
        def on_load(ctx: PluginContext) -> None
        def on_unload(ctx: PluginContext) -> None
    """

    GROUP = "teridex.plugins"

    def __init__(
        self,
        registry: PluginRegistry,
        event_bus: EventBus,
        *,
        enabled: Iterable[str] | None = None,
        disabled: Iterable[str] | None = None,
        services: dict[str, Any] | None = None,
    ) -> None:
        self._registry = registry
        self._bus = event_bus
        self._enabled = set(enabled or [])
        self._disabled = set(disabled or [])
        self._services = services or {}
        self._instances: dict[str, Any] = {}
        self._contexts: dict[str, PluginContext] = {}

    def _is_allowed(self, plugin_id: str) -> bool:
        if plugin_id in self._disabled:
            return False
        return not (self._enabled and plugin_id not in self._enabled)

    def discover(self) -> list[EntryPoint]:
        return list(entry_points(group=self.GROUP))

    def load_all(self) -> None:
        for ep in self.discover():
            try:
                self.load_entry_point(ep)
            except PluginLoadError:
                logger.exception("plugin_load_failed", entry_point=ep.name)

    def load_entry_point(self, ep: EntryPoint) -> None:
        try:
            factory = ep.load()
            plugin = factory()
        except Exception as exc:
            raise PluginLoadError(
                f"failed to instantiate plugin {ep.name!r}", context={"error": str(exc)}
            ) from exc
        self._register(plugin)

    def load_instance(self, plugin: Any) -> None:
        self._register(plugin)

    def _register(self, plugin: Any) -> None:
        manifest = getattr(plugin, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise PluginLoadError(
                "plugin missing PluginManifest at `.manifest`",
                context={"plugin_repr": repr(plugin)},
            )
        if not self._is_allowed(manifest.id):
            logger.info("plugin_skipped", plugin_id=manifest.id)
            return
        self._registry.add_plugin(manifest)
        ctx = PluginContext(
            plugin_id=manifest.id,
            event_bus=self._bus,
            registry=self._registry,
            services=self._services,
        )
        self._contexts[manifest.id] = ctx
        on_load = getattr(plugin, "on_load", None)
        if callable(on_load):
            try:
                on_load(ctx)
            except Exception as exc:
                self._registry.remove_plugin(manifest.id)
                self._contexts.pop(manifest.id, None)
                raise PluginLoadError(
                    f"on_load failed for plugin {manifest.id!r}",
                    context={"error": str(exc)},
                ) from exc
        self._instances[manifest.id] = plugin
        self._bus.publish(PluginLoaded(plugin_id=manifest.id))
        logger.info("plugin_loaded", plugin_id=manifest.id, version=manifest.version)

    def context_for(self, plugin_id: str) -> PluginContext:
        """Return the long-lived context bound to a loaded plugin.

        Used by the host app to invoke ``Panel.factory(ctx)`` with the same
        context the plugin received in ``on_load`` — so panel widgets and
        hooks share state.
        """
        try:
            return self._contexts[plugin_id]
        except KeyError as exc:
            raise PluginError(
                f"plugin not loaded: {plugin_id!r}", context={"plugin_id": plugin_id}
            ) from exc

    def unload(self, plugin_id: str) -> None:
        plugin = self._instances.pop(plugin_id, None)
        if plugin is None:
            raise PluginError(f"plugin not loaded: {plugin_id!r}", context={"plugin_id": plugin_id})
        on_unload = getattr(plugin, "on_unload", None)
        ctx = self._contexts.pop(plugin_id, None)
        if callable(on_unload):
            if ctx is None:
                # No tracked context — the plugin was never fully loaded.
                # Skip on_unload rather than handing it a fabricated context
                # that shares none of the state it saw in on_load.
                logger.warning("plugin_unload_without_context", plugin_id=plugin_id)
            else:
                try:
                    on_unload(ctx)
                except Exception:
                    logger.exception("plugin_on_unload_failed", plugin_id=plugin_id)
        self._registry.remove_plugin(plugin_id)
        self._bus.publish(PluginUnloaded(plugin_id=plugin_id))
