"""History modal smoke test."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from textual.widgets import ListView  # noqa: E402

from teridex_core.config import TeridexConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_engine.history import HistoryEntry  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402
from teridex_tui.screens.history import HistoryModal  # noqa: E402


@pytest.mark.asyncio
async def test_history_modal_opens_empty() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("ctrl+g")
        await pilot.pause()
        modals = [s for s in app.screen_stack if isinstance(s, HistoryModal)]
        assert modals, "history modal did not appear"
        await pilot.press("escape")
        await pilot.pause()
        assert not any(isinstance(s, HistoryModal) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_history_modal_lists_entry_after_insert() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.state.history is not None
        await app.state.history.add(
            HistoryEntry(
                query_id="qx",
                connection_label="sqlite:///:memory:",
                sql="SELECT 'hello from history'",
                status="succeeded",
                duration_ms=1.0,
                rows=1,
            )
        )
        await pilot.press("ctrl+g")
        await pilot.pause()
        modal = next(s for s in app.screen_stack if isinstance(s, HistoryModal))
        listing = modal.query_one("#history-list", ListView)
        assert len(listing.children) >= 1
        await pilot.press("escape")
