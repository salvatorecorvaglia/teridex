from __future__ import annotations

import pytest

from teridex_adapters.registry import default_registry, reset_default_registry
from teridex_core.errors import AdapterError


def test_registry_has_known_adapters() -> None:
    reg = default_registry()
    names = reg.names()
    # sqlite is required (aiosqlite is a hard dep of engine); duckdb depends on extra
    assert "sqlite" in names


def test_registry_unknown_scheme_raises() -> None:
    reg = default_registry()
    with pytest.raises(AdapterError):
        reg.for_scheme("oracle")


def test_default_registry_is_cached_until_reset() -> None:
    first = default_registry()
    assert default_registry() is first
    reset_default_registry()
    assert default_registry() is not first
