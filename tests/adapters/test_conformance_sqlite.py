"""SQLite runs the shared adapter conformance suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from teridex_adapters.sqlite_adapter import SQLiteAdapter
from teridex_core.models.connection import Dsn
from tests.adapters._conformance import AdapterConformance

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class TestSQLiteConformance(AdapterConformance):
    @pytest.fixture
    async def adapter(self) -> AsyncIterator[SQLiteAdapter]:
        a = SQLiteAdapter()
        await a.connect(Dsn.parse("sqlite:///:memory:"))
        try:
            yield a
        finally:
            await a.close()
