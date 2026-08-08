"""Shared behaviour for Teridex's modal screens.

Every modal in the app answers the same two keys — ``escape`` cancels,
``enter`` submits — and each one used to hand-roll that, which is how they
drifted apart (only one of them, for instance, deferred ``enter`` to a focused
list). Subclasses implement :meth:`submit` and inherit the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from textual.screen import ModalScreen

if TYPE_CHECKING:
    from textual.events import Key

ResultT = TypeVar("ResultT")


class BaseModal(ModalScreen[ResultT | None]):
    """Modal that cancels on ``escape`` and submits on ``enter``."""

    def submit(self) -> None:
        """Resolve the modal with a value. Subclasses must override."""
        raise NotImplementedError

    def cancel(self) -> None:
        self.dismiss(None)

    def handles_enter_itself(self) -> bool:
        """True when the focused widget should get ``enter`` instead.

        A focused list, for example, turns ``enter`` into its own selection
        event, and intercepting it here would submit twice.
        """
        return False

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.cancel()
        elif event.key == "enter" and not self.handles_enter_itself():
            event.stop()
            self.submit()
