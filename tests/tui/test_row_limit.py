"""Tests for RowLimitModal and dynamic row limit setting."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

from teridex_core.config import TeridexConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402
from teridex_tui.screens.row_limit import RowLimitModal  # noqa: E402


@pytest.mark.asyncio
async def test_row_limit_modal_lifecycle() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()

        # Trigger action to set row limit
        await app.action_set_row_limit()
        await pilot.pause()

        modals = [s for s in app.screen_stack if isinstance(s, RowLimitModal)]
        assert modals, "row limit modal did not appear"

        # Set limit input value
        modal = modals[0]
        inp = modal.query_one("#limit-input", Input)
        inp.value = "456"

        # Submit
        await pilot.press("enter")
        await pilot.pause()

        assert not any(isinstance(s, RowLimitModal) for s in app.screen_stack)
        assert app.cfg.ui.max_display_rows == 456
        assert app._results().max_rows == 456
