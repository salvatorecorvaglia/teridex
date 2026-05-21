"""Smoke test: app boots, mounts, and can be torn down."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from teridex_core.config import TeridexConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402


@pytest.mark.asyncio
async def test_app_boots_in_memory_sqlite() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        # Give startup tasks a chance to settle.
        await pilot.pause()
        assert app.state.adapter is not None
        assert app.state.adapter.connected
