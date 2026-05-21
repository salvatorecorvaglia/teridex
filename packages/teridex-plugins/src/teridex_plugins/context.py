"""PluginContext — the narrow runtime surface handed to each plugin."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from teridex_core.events import Event, EventBus
from teridex_core.logging import get_logger

if TYPE_CHECKING:
    from teridex_plugins.api import Command, Panel
    from teridex_plugins.registry import PluginRegistry

logger = get_logger(__name__)
E = TypeVar("E", bound=Event)


class PluginContext:
    """Stable runtime API for plugins.

    Intentionally narrow: plugins should not reach into the DI container. We
    expose only what's needed to react to events and contribute UI/commands.
    """

    def __init__(
        self,
        *,
        plugin_id: str,
        event_bus: EventBus,
        registry: "PluginRegistry",
        services: dict[str, Any] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self._bus = event_bus
        self._registry = registry
        self._services = services or {}
        self.logger = logger.bind(plugin_id=plugin_id)

    def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None:
        self._bus.subscribe(event_type, handler)

    def publish(self, event: Event) -> None:
        self._bus.publish(event)

    def register_command(self, command: "Command") -> None:
        self._registry.add_command(self.plugin_id, command)

    def register_panel(self, panel: "Panel") -> None:
        self._registry.add_panel(self.plugin_id, panel)

    def get_service(self, name: str) -> Any:
        return self._services.get(name)
