"""Help modal smoke test."""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from teridex_core.config import TeridexConfig  # noqa: E402
from teridex_core.models.connection import Dsn  # noqa: E402
from teridex_tui.app import TeridexApp  # noqa: E402
from teridex_tui.screens.help import HelpModal  # noqa: E402


@pytest.mark.asyncio
async def test_help_modal_opens_and_dismisses() -> None:
    app = TeridexApp(config=TeridexConfig(), initial_dsn=Dsn.parse("sqlite:///:memory:"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        # The modal should now be on the screen stack.
        assert any(isinstance(s, HelpModal) for s in app.screen_stack)
        await pilot.press("escape")
        await pilot.pause()
        assert not any(isinstance(s, HelpModal) for s in app.screen_stack)
