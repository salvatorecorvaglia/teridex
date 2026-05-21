"""Shared mutable runtime state for the TUI.

Keeping this in one place keeps the screen and widgets thin and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from teridex_core.events import EventBus
from teridex_core.models.connection import Dsn
from teridex_core.protocols.adapter import DatabaseAdapter
from teridex_engine.executor import QueryExecutor
from teridex_engine.history import QueryHistory
from teridex_engine.introspector import Introspector
from teridex_plugins.registry import PluginRegistry


@dataclass
class AppState:
    bus: EventBus
    plugins: PluginRegistry
    dsn: Dsn | None = None
    adapter: DatabaseAdapter | None = None
    executor: QueryExecutor | None = None
    introspector: Introspector | None = None
    history: QueryHistory | None = None

    @property
    def connected(self) -> bool:
        return self.adapter is not None and self.adapter.connected  # type: ignore[attr-defined]
