"""Typed exception hierarchy for Teridex.

Every error carries a stable, machine-readable ``code`` for telemetry and
plugin-side handling. Use ``code`` for branching, ``message`` for humans.
"""

from __future__ import annotations

from typing import Any


class TeridexError(Exception):
    """Base class for all Teridex errors."""

    code: str = "teridex.unknown"

    def __init__(self, message: str, /, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = dict(context) if context else {}

    def __str__(self) -> str:
        if self.context:
            return f"[{self.code}] {self.message} :: {self.context}"
        return f"[{self.code}] {self.message}"


class ConfigError(TeridexError):
    code = "teridex.config"


class AdapterError(TeridexError):
    code = "teridex.adapter"


class ConnectionError(AdapterError):  # noqa: A001 - intentional shadow at module scope
    code = "teridex.adapter.connection"


class QueryError(TeridexError):
    code = "teridex.query"


class QueryCancelledError(QueryError):
    code = "teridex.query.cancelled"


class QueryTimeoutError(QueryError):
    code = "teridex.query.timeout"


class IntrospectionError(AdapterError):
    code = "teridex.adapter.introspection"


class PluginError(TeridexError):
    code = "teridex.plugin"


class PluginLoadError(PluginError):
    code = "teridex.plugin.load"


class DependencyResolutionError(TeridexError):
    code = "teridex.di.resolution"
