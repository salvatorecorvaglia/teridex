"""Teridex core abstractions."""

from teridex_core.errors import (
    AdapterError,
    ConfigError,
    PluginError,
    QueryCancelledError,
    QueryError,
    TeridexError,
)
from teridex_core.result import Err, Ok, Result

__all__ = [
    "AdapterError",
    "ConfigError",
    "Err",
    "Ok",
    "PluginError",
    "QueryCancelledError",
    "QueryError",
    "Result",
    "TeridexError",
]

__version__ = "0.1.2"
