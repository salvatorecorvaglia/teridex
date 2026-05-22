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


@pytest.mark.asyncio
async def test_run_query_rejects_reentry_while_in_flight() -> None:
    # Regression: a second run while one is in flight must not clobber the
    # current run handle — it should be rejected up front.
    app = TeridexApp(config=TeridexConfig())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._query_in_flight = True
        await app.action_run_query()
        assert "already running" in app._status().message
