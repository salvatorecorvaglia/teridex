"""Teridex core abstractions."""

from teridex_core.errors import (
    AdapterError,
    ConfigError,
    PluginError,
    QueryCancelledError,
    QueryError,
    TeridexError,
)

__all__ = [
    "AdapterError",
    "ConfigError",
    "PluginError",
    "QueryCancelledError",
    "QueryError",
    "TeridexError",
]

__version__ = "1.0.0"
