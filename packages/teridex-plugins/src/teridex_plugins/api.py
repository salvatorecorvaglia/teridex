"""Public plugin API surface.

Plugins import only from here. Internal details (loader, registry) are
intentionally hidden so we can refactor without breaking plugins.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeVar

if TYPE_CHECKING:
    from teridex_plugins.context import PluginContext

PanelPlacement = Literal["left", "right", "bottom"]

F = TypeVar("F", bound=Callable[..., Any])

_HOOK_ATTR = "__teridex_hook__"


def hook(event: str) -> Callable[[F], F]:
    """Mark a function as a hook for a Teridex internal event.

    The plugin's ``on_load`` is responsible for registering hook-decorated
    methods with the runtime via :meth:`PluginContext.subscribe`. The
    decorator simply tags the function so the runtime can discover it.

    Example::

        @hook("query.before_execute")
        async def warn_on_drop(self, ctx, sql: str) -> None:
            ...
    """

    def _wrap(fn: F) -> F:
        setattr(fn, _HOOK_ATTR, event)
        return fn

    return _wrap


def is_hook(fn: object) -> bool:
    return hasattr(fn, _HOOK_ATTR)


def hook_event(fn: object) -> str:
    return str(getattr(fn, _HOOK_ATTR))


CommandHandler = Callable[["PluginContext"], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Command:
    """User-invocable action surfaced in the command palette."""

    id: str
    title: str
    handler: CommandHandler
    default_binding: str | None = None
    description: str = ""
    category: str = "Plugin"


@dataclass(frozen=True, slots=True)
class Panel:
    """A dockable panel contributed by a plugin.

    ``factory`` returns a Textual widget instance; we use ``Any`` here to
    keep this module dependency-free of Textual.
    """

    id: str
    title: str
    placement: PanelPlacement
    factory: Callable[["PluginContext"], Any]
    initial_size: int = 30
    keys: list[str] = field(default_factory=list)
