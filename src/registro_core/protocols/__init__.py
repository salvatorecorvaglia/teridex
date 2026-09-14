"""Public protocols (structural interfaces) defining Teridex extension points."""

from teridex_core.protocols.adapter import DatabaseAdapter, Transaction
from teridex_core.protocols.plugin import Plugin, PluginManifest

__all__ = [
    "DatabaseAdapter",
    "Plugin",
    "PluginManifest",
    "Transaction",
]
