"""Registro core abstractions."""

from registro_core.errors import (
    AdapterError,
    ConfigError,
    PluginError,
    QueryCancelledError,
    QueryError,
    RegistroError,
)

__all__ = [
    "AdapterError",
    "ConfigError",
    "PluginError",
    "QueryCancelledError",
    "QueryError",
    "RegistroError",
]

__version__ = "2.0.0"
