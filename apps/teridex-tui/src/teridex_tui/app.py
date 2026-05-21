"""TeridexApp — the top-level Textual application.

Responsibilities:
* Build the dependency graph (event bus, plugin registry, adapter, executor).
* Wire keyboard actions to engine operations.
* React to engine events (status bar updates, results streaming).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding

from teridex_adapters import create_adapter_for_dsn
from teridex_core.config import TeridexConfig, load_config
from teridex_core.errors import QueryCancelledError, QueryError, TeridexError
from teridex_core.events import (
    EventBus,
    QueryCompleted,
    QueryFailed,
    QueryStarted,
)
from teridex_core.logging import configure_logging, get_logger
from teridex_engine.executor import QueryExecutor, QueryRun
from teridex_engine.history import HistoryEntry, QueryHistory
from teridex_engine.introspector import Introspector
from teridex_plugins.context import PluginContext
from teridex_plugins.loader import PluginLoader
from teridex_plugins.registry import PluginRegistry
from teridex_tui.builtin_commands import BUILTIN_COMMANDS
from teridex_tui.events import RunActionRequested
from teridex_tui.keymaps import DEFAULT_BINDINGS, VIM_BINDINGS
from teridex_tui.screens.command_palette import CommandPaletteScreen
from teridex_tui.screens.main import MainScreen
from teridex_tui.state import AppState
from teridex_tui.themes import THEMES
from teridex_tui.widgets import QueryTabs, ResultsTable, SchemaTree, StatusBar

if TYPE_CHECKING:
    from teridex_core.models.connection import Dsn

logger = get_logger(__name__)


class TeridexApp(App[None]):
    """The Teridex Textual application."""

    CSS_PATH = "teridex.tcss"
    TITLE = "Teridex"

    # Class-level bindings — Textual reads these at class-creation time.
    # Vim-mode adds extra bindings dynamically in __init__ via bind().
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding(k, a, d) for (k, a, d) in DEFAULT_BINDINGS
    ]

    def __init__(
        self,
        config: TeridexConfig | None = None,
        initial_dsn: Dsn | None = None,
    ) -> None:
        super().__init__()
        self.cfg = config or load_config()
        configure_logging(level=self.cfg.logging.level, json=self.cfg.logging.json_lines)
        self.state = AppState(bus=EventBus(), plugins=PluginRegistry())
        self._initial_dsn = initial_dsn
        self._current_run: QueryRun | None = None
        self._palette_task: asyncio.Task[None] | None = None
        if self.cfg.ui.keymap == "vim":
            for key, action, desc in VIM_BINDINGS:
                if (key, action, desc) in DEFAULT_BINDINGS:
                    continue
                self.bind(key, action, description=desc)

    # ---- lifecycle -----------------------------------------------------

    def compose(self) -> ComposeResult:
        yield MainScreen()

    async def on_mount(self) -> None:
        self._apply_theme()
        await self._load_plugins()
        self._wire_event_listeners()
        if self._initial_dsn is not None:
            await self._connect(self._initial_dsn)

    async def on_unmount(self) -> None:
        if self.state.history is not None:
            await self.state.history.close()
        if self.state.adapter is not None:
            await self.state.adapter.close()
        await self.state.bus.close()

    # ---- setup helpers ------------------------------------------------

    def _apply_theme(self) -> None:
        from textual.theme import Theme as TxTheme  # noqa: PLC0415

        theme = THEMES.get(self.cfg.ui.theme, THEMES["monokai"])
        tx = TxTheme(
            name=f"teridex-{theme.name}",
            primary=theme.primary,
            accent=theme.accent,
            success=theme.success,
            warning=theme.warning,
            error=theme.error,
            background=theme.background,
            foreground=theme.foreground,
            surface=theme.surface,
            dark=True,
        )
        self.register_theme(tx)
        self.theme = tx.name
        logger.debug("theme_applied", theme=theme.name)

    async def _load_plugins(self) -> None:
        loader = PluginLoader(
            self.state.plugins,
            self.state.bus,
            enabled=self.cfg.plugins.enabled or None,
            disabled=self.cfg.plugins.disabled or None,
        )
        loader.load_all()

    def _wire_event_listeners(self) -> None:
        async def on_started(ev: QueryStarted) -> None:
            self._status().message = f"running… ({ev.sql_preview})"

        async def on_completed(ev: QueryCompleted) -> None:
            bar = self._status()
            bar.rows = ev.rows
            bar.duration_ms = ev.duration_ms
            bar.message = "ok"

        async def on_failed(ev: QueryFailed) -> None:
            self._status().message = f"[red]{ev.error_code}: {ev.message}[/]"

        async def on_action(ev: RunActionRequested) -> None:
            await self.run_action(ev.action)

        self.state.bus.subscribe(QueryStarted, on_started)
        self.state.bus.subscribe(QueryCompleted, on_completed)
        self.state.bus.subscribe(QueryFailed, on_failed)
        self.state.bus.subscribe(RunActionRequested, on_action)

    async def _connect(self, dsn: Dsn) -> None:
        adapter = create_adapter_for_dsn(dsn)
        await adapter.connect(dsn)
        self.state.dsn = dsn
        self.state.adapter = adapter
        self.state.executor = QueryExecutor(adapter, self.state.bus)
        self.state.introspector = Introspector(adapter, self.state.bus)
        # History store
        history = QueryHistory(
            Path.home() / ".teridex" / "history.db",
            max_entries=self.cfg.engine.max_history_entries,
        )
        await history.open()
        self.state.history = history
        bar = self._status()
        bar.connection = dsn.render(mask_password=True)
        await self.action_refresh_schema()

    # ---- widget shortcuts ---------------------------------------------

    def _status(self) -> StatusBar:
        return self.query_one(StatusBar)

    def _tabs(self) -> QueryTabs:
        return self.query_one(QueryTabs)

    def _results(self) -> ResultsTable:
        return self.query_one(ResultsTable)

    def _tree(self) -> SchemaTree:
        return self.query_one(SchemaTree)

    # ---- actions ------------------------------------------------------

    async def action_run_query(self) -> None:
        if self.state.executor is None:
            self._status().message = "[yellow]not connected[/]"
            return
        editor = self._tabs().current_editor
        if editor is None or not editor.sql.strip():
            return
        sql = editor.sql
        results = self._results()
        results.reset()
        try:
            self._current_run = await self.state.executor.run(
                sql, batch_size=self.cfg.ui.row_batch_size
            )
        except QueryError as exc:
            self._status().message = f"[red]{exc}[/]"
            return
        try:
            async for batch in self._current_run.rows:
                results.feed(batch)
        except QueryCancelledError:
            self._status().message = "[yellow]cancelled[/]"
        except TeridexError as exc:
            self._status().message = f"[red]{exc}[/]"
        finally:
            await self._record_history(sql)
            self._current_run = None

    async def action_cancel_query(self) -> None:
        if self._current_run is not None and self.state.executor is not None:
            await self.state.executor.cancel(self._current_run)

    async def action_refresh_schema(self) -> None:
        if self.state.introspector is None:
            return
        try:
            snap = await self.state.introspector.refresh()
        except TeridexError as exc:
            self._status().message = f"[red]schema: {exc}[/]"
            return
        self._tree().populate(snap)

    async def action_new_tab(self) -> None:
        self._tabs().new_tab()

    async def action_close_tab(self) -> None:
        self._tabs().close_current()

    async def action_command_palette(self) -> None:  # type: ignore[override]
        # Textual supports async actions at runtime; its stubs only declare
        # the sync signature. Mypy override-suppress is intentional.
        commands = [*BUILTIN_COMMANDS, *self.state.plugins.all_commands()]
        result = await self.push_screen_wait(CommandPaletteScreen(commands))
        if result is not None:
            ctx = PluginContext(
                plugin_id="builtin",
                event_bus=self.state.bus,
                registry=self.state.plugins,
            )
            self._palette_task = asyncio.ensure_future(result.handler(ctx))

    async def action_help(self) -> None:
        self._status().message = "see docs/ or press Ctrl+P for commands"

    # ---- history ------------------------------------------------------

    async def _record_history(self, sql: str) -> None:
        if self.state.history is None or self._current_run is None:
            return
        run = self._current_run
        await self.state.history.add(
            HistoryEntry(
                query_id=run.query_id,
                connection_label=(
                    self.state.dsn.render(mask_password=True) if self.state.dsn else "?"
                ),
                sql=sql,
                status=run.status.value,
                duration_ms=run.duration_ms,
                rows=run.rows_emitted,
            )
        )
