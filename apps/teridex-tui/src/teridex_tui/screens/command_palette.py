"""Fuzzy command palette (Ctrl+P)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from teridex_plugins.api import Command

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Key


@dataclass(slots=True)
class _Entry:
    cmd: Command

    @property
    def label(self) -> str:
        binding = f"  [dim]({self.cmd.default_binding})[/]" if self.cmd.default_binding else ""
        return f"[b]{self.cmd.title}[/]{binding}\n[dim]{self.cmd.description or self.cmd.id}[/]"


class CommandPaletteScreen(ModalScreen[Command | None]):
    DEFAULT_CSS = ""

    def __init__(self, commands: list[Command]) -> None:
        super().__init__()
        self._all = commands

    def compose(self) -> ComposeResult:
        with Vertical(id="command-palette"):
            yield Static("[b]Command palette[/b]", id="palette-title")
            yield Input(placeholder="Search commands…", id="palette-input")
            yield ListView(id="palette-list")

    def on_mount(self) -> None:
        self._refresh("")
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh(event.value)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._submit()
        elif event.key in {"up", "down"}:
            lst = self.query_one("#palette-list", ListView)
            lst.post_message(event)

    def _refresh(self, q: str) -> None:
        lst = self.query_one("#palette-list", ListView)
        lst.clear()
        ranked: list[Command]
        if not q:
            ranked = list(self._all)
        else:
            # process.extract with a dict input returns (choice, score, key).
            # ``limit=None`` ranks every command so no match is silently hidden.
            id_to_cmd = {c.id: c for c in self._all}
            matches = process.extract(
                q,
                {c.id: c.title for c in self._all},
                scorer=fuzz.WRatio,
                limit=None,
            )
            ranked = [id_to_cmd[key] for (_title, _score, key) in matches]
        for cmd in ranked:
            lst.append(ListItem(Static(_Entry(cmd).label), id=f"cmd-{cmd.id}"))
        self.query_one("#palette-title", Static).update(
            f"[b]Command palette[/b]  [dim]{len(ranked)}/{len(self._all)}[/]"
        )

    def _submit(self) -> None:
        lst = self.query_one("#palette-list", ListView)
        item = lst.highlighted_child
        if item is None or item.id is None:
            self.dismiss(None)
            return
        cmd_id = item.id.removeprefix("cmd-")
        cmd = next((c for c in self._all if c.id == cmd_id), None)
        self.dismiss(cmd)
