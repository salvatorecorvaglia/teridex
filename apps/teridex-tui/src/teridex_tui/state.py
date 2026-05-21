"""Shared mutable runtime state for the TUI.

Keeping this in one place keeps the screen and widgets thin and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teridex_core.events import EventBus
    from teridex_core.models.connection import Dsn
    from teridex_core.protocols.adapter import DatabaseAdapter
    from teridex_engine.history import QueryHistory
    from teridex_engine.introspector import Introspector
    from teridex_engine.pool import ConnectionPool
    from teridex_plugins.registry import PluginRegistry


@dataclass
class AppState:
    bus: EventBus
    plugins: PluginRegistry
    dsn: Dsn | None = None
    # Adapter dedicated to schema introspection — never shared with query
    # execution, so a long SELECT cannot block a refresh.
    adapter: DatabaseAdapter | None = None
    # Bounded pool of execution adapters. Each `action_run_query` acquires
    # one for the lifetime of its stream.
    pool: ConnectionPool | None = None
    introspector: Introspector | None = None
    history: QueryHistory | None = None

    @property
    def connected(self) -> bool:
        return self.adapter is not None and self.adapter.connected  # type: ignore[attr-defined]
