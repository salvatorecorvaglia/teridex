from __future__ import annotations

import pytest

from teridex_core.errors import AdapterError
from teridex_adapters.registry import default_registry


def test_registry_has_known_adapters() -> None:
    reg = default_registry()
    names = reg.names()
    # sqlite is required (aiosqlite is a hard dep of engine); duckdb depends on extra
    assert "sqlite" in names


def test_registry_unknown_scheme_raises() -> None:
    reg = default_registry()
    with pytest.raises(AdapterError):
        reg.for_scheme("oracle")
