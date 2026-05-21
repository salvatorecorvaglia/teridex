"""Single-line status bar at the bottom of the screen."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = ""

    connection: reactive[str] = reactive("disconnected")
    mode: reactive[str] = reactive("NORMAL")
    message: reactive[str] = reactive("")
    rows: reactive[int] = reactive(0)
    duration_ms: reactive[float] = reactive(0.0)

    def __init__(self) -> None:
        super().__init__(id="status-bar")

    def render(self) -> str:
        parts = [
            f"⎈ {self.connection}",
            f"⌨ {self.mode}",
            f"≡ {self.rows} rows",
            f"⏱ {self.duration_ms:.1f} ms",
        ]
        if self.message:
            parts.append(self.message)
        return "  │  ".join(parts)
