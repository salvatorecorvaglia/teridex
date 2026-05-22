"""TeridexApp — the top-level Textual application.

Responsibilities:
* Build the dependency graph (event bus, plugin registry, adapter, executor).
* Wire keyboard actions to engine operations.
* React to engine events (status bar updates, results streaming).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
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
from teridex_engine.pool import ConnectionPool
from teridex_plugins.context import PluginContext
from teridex_plugins.loader import PluginLoader
from teridex_plugins.registry import PluginRegistry
from teridex_tui.builtin_commands import BUILTIN_COMMANDS
from teridex_tui.events import RunActionRequested
from teridex_tui.keymaps import DEFAULT_BINDINGS, VIM_BINDINGS
from teridex_tui.screens.command_palette import CommandPaletteScreen
from teridex_tui.screens.help import HelpModal
from teridex_tui.screens.history import HistoryModal
from teridex_tui.screens.main import MainScreen
from teridex_tui.state import AppState
from teridex_tui.themes import THEMES
from teridex_tui.widgets import ActionBar, QueryTabs, ResultsTable, SchemaTree, StatusBar

if TYPE_CHECKING:
    from textual.widget import Widget

    from teridex_adapters.base import AbstractAdapter
    from teridex_core.models.connection import Dsn
    from teridex_plugins.api import Command

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
        log_dir = Path.home() / ".teridex"
        log_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(
            level=self.cfg.logging.level,
            json=self.cfg.logging.json_lines,
            log_file=log_dir / "teridex.log",
            force=True,
        )
        self.state = AppState(bus=EventBus(), plugins=PluginRegistry())
        self._initial_dsn = initial_dsn
        self._current_run: QueryRun | None = None
        self._run_executor: QueryExecutor | None = None
        self._query_in_flight = False
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
        self._apply_border_titles()
        await self._load_plugins()
        await self._mount_plugin_panels()
        self._wire_event_listeners()
        self._results().max_rows = self.cfg.ui.max_display_rows
        self._status().mode = "VIM" if self.cfg.ui.keymap == "vim" else "NORMAL"
        # Wire ActionBar limit from config
        with contextlib.suppress(Exception):
            self._action_bar().limit = self.cfg.ui.max_display_rows or 500
        if self._initial_dsn is not None:
            self.run_worker(self._connect(self._initial_dsn))

    async def on_unmount(self) -> None:
        if self._palette_task is not None and not self._palette_task.done():
            self._palette_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._palette_task
        if self.state.history is not None:
            await self.state.history.close()
        if self.state.pool is not None:
            await self.state.pool.close()
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

    def _apply_border_titles(self) -> None:
        """Set border titles on panels."""
        with contextlib.suppress(Exception):
            self.query_one("#sidebar").border_title = "Data Catalog"
        with contextlib.suppress(Exception):
            self.query_one("#editor-panel").border_title = "Query Editor"
        with contextlib.suppress(Exception):
            self.query_one("#results-panel").border_title = "Query Results"

    async def _load_plugins(self) -> None:
        # Pass eagerly-available services. Late-bound ones (executor,
        # introspector, history) are added via ``update_services`` once
        # ``_connect`` runs — the cached PluginContext is the same object.
        loader = PluginLoader(
            self.state.plugins,
            self.state.bus,
            enabled=self.cfg.plugins.enabled or None,
            disabled=self.cfg.plugins.disabled or None,
            services={
                "event_bus": self.state.bus,
                "plugins": self.state.plugins,
                "config": self.cfg,
            },
        )
        loader.load_all()
        self._loader = loader

    def _publish_connection_services(self) -> None:
        """Push connect-time services into every loaded plugin's context."""
        loader = getattr(self, "_loader", None)
        if loader is None:
            return
        late = {
            "adapter": self.state.adapter,
            "pool": self.state.pool,
            "introspector": self.state.introspector,
            "history": self.state.history,
        }
        for manifest in self.state.plugins.manifests():
            loader.context_for(manifest.id).update_services(**late)

    async def _mount_plugin_panels(self) -> None:
        from textual.containers import Vertical  # noqa: PLC0415

        loader = getattr(self, "_loader", None)
        if loader is None:
            return
        rails: dict[str, list[Widget]] = {
            "left": [],
            "right": [],
            "bottom": [],
        }
        for plugin_id, panel in self.state.plugins.panels_by_plugin():
            ctx = loader.context_for(plugin_id)
            try:
                widget = panel.factory(ctx)
            except Exception:
                logger.exception("plugin_panel_factory_failed", plugin_id=plugin_id)
                continue
            rails[panel.placement].append(widget)

        if rails["left"]:
            sidebar = self.query_one("#sidebar")
            for w in rails["left"]:
                await sidebar.mount(w)
        if rails["right"]:
            grid = self.query_one("#main-grid")
            grid.add_class("with-right")
            rail = Vertical(id="right-rail")
            # Mount before the status bar so grid ordering stays correct.
            await grid.mount(rail, before=self._status())
            for w in rails["right"]:
                await rail.mount(w)
        if rails["bottom"]:
            grid = self.query_one("#main-grid")
            grid.add_class("with-bottom")
            rail = Vertical(id="bottom-rail")
            await grid.mount(rail, before=self._status())
            for w in rails["bottom"]:
                await rail.mount(w)

    def _wire_event_listeners(self) -> None:
        async def on_started(ev: QueryStarted) -> None:
            self._status().message = f"running… ({ev.sql_preview})"

        async def on_completed(ev: QueryCompleted) -> None:
            bar = self._status()
            bar.rows = ev.rows
            bar.duration_ms = ev.duration_ms
            bar.has_run = True
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
        bar = self._status()
        bar.message = "connecting…"
        try:

            async def _factory(d: Dsn) -> AbstractAdapter:
                a = create_adapter_for_dsn(d)
                await a.connect(d)
                return a

            # Dedicated adapter for schema introspection — never shared with
            # query execution, so a long SELECT cannot block ``Ctrl+R``.
            introspect_adapter = await _factory(dsn)

            # Bounded pool of execution adapters. ``action_run_query`` acquires
            # one for the lifetime of its stream and returns it on exit.
            pool = ConnectionPool(dsn, _factory, size=self.cfg.engine.pool_size)

            self.state.dsn = dsn
            self.state.adapter = introspect_adapter
            self.state.pool = pool
            self.state.introspector = Introspector(introspect_adapter, self.state.bus)
            # History store
            history = QueryHistory(
                Path.home() / ".teridex" / "history.db",
                max_entries=self.cfg.engine.max_history_entries,
            )
            await history.open()
            self.state.history = history
            self._publish_connection_services()
            bar.connection = dsn.render(mask_password=True)
            await self.action_refresh_schema()
            # Clear transient message so the footer shows "Database Connected."
            bar.message = ""
        except Exception as exc:
            logger.exception("connection_failed", dsn=dsn.render(mask_password=True))
            bar.message = f"[red]Connection failed: {exc}[/]"

    # ---- widget shortcuts ---------------------------------------------

    def _status(self) -> StatusBar:
        return self.query_one(StatusBar)

    def _tabs(self) -> QueryTabs:
        return self.query_one(QueryTabs)

    def _results(self) -> ResultsTable:
        return self.query_one(ResultsTable)

    def _tree(self) -> SchemaTree:
        return self.query_one(SchemaTree)

    def _action_bar(self) -> ActionBar:
        return self.query_one(ActionBar)

    # ---- actions ------------------------------------------------------

    async def action_run_query(self) -> None:
        if self._query_in_flight:
            self._status().message = "[yellow]a query is already running[/]"
            return
        if self.state.pool is None:
            self._status().message = "[yellow]not connected[/]"
            return
        editor = self._tabs().current_editor
        if editor is None or not editor.sql.strip():
            self._status().message = "[yellow]nothing to run[/]"
            return
        sql = editor.sql
        results = self._results()
        results.reset()
        results.loading = True
        self._status().truncated = False
        self._query_in_flight = True

        # Acquire a dedicated adapter from the pool for this run; release
        # it in ``finally`` so a cancellation never leaks the slot.
        try:
            async with self.state.pool.acquire() as adapter:
                executor = QueryExecutor(adapter, self.state.bus)
                self._run_executor = executor
                try:
                    self._current_run = await executor.run(
                        sql, batch_size=self.cfg.ui.row_batch_size
                    )
                except QueryError as exc:
                    results.loading = False
                    self._status().message = f"[red]{exc}[/]"
                    return
                cancelled = False
                try:
                    async for batch in self._current_run.rows:
                        results.loading = False
                        results.feed(batch)
                except QueryCancelledError:
                    cancelled = True
                    self._status().message = "[yellow]cancelled[/]"
                except TeridexError as exc:
                    self._status().message = f"[red]{exc}[/]"
                finally:
                    results.loading = False
                    results.mark_done(cancelled=cancelled)
                    self._status().truncated = results.truncated
                    await self._record_history(sql)
        except Exception as exc:
            # Failure before/around streaming — e.g. pool acquisition or
            # connection setup. Clear the spinner so the table isn't stuck.
            logger.exception("run_query_failed")
            results.loading = False
            self._status().message = f"[red]{exc}[/]"
        finally:
            self._current_run = None
            self._run_executor = None
            self._query_in_flight = False

    async def action_copy_cell(self) -> None:
        text = self._results().current_cell_text()
        if text is None:
            self._status().message = "[yellow]nothing to copy[/]"
            return
        self.copy_to_clipboard(text)
        self._status().message = "copied cell"

    async def action_export_csv(self) -> None:
        results = self._results()
        if results.row_count == 0:
            self._status().message = "[yellow]nothing to export[/]"
            return
        path = Path.home() / ".teridex" / "exports" / f"export-{int(time.time())}.csv"
        try:
            n = results.export_csv(path)
        except OSError as exc:
            self._status().message = f"[red]export failed: {exc}[/]"
            return
        self._status().message = f"exported {n} row{'s' if n != 1 else ''} → {path}"

    async def action_cancel_query(self) -> None:
        # Snapshot both references before awaiting: action_run_query's finally
        # block can null them concurrently between the check and the await.
        run = self._current_run
        executor = self._run_executor
        if run is not None and executor is not None:
            await executor.cancel(run)

    async def action_refresh_schema(self) -> None:
        if self.state.introspector is None:
            return
        self._status().message = "refreshing schema…"
        try:
            snap = await self.state.introspector.refresh(lazy=True)
        except TeridexError as exc:
            self._status().message = f"[red]schema: {exc}[/]"
            return
        self._tree().populate(snap)
        self._status().message = f"schema refreshed · {snap.object_count} object(s)"

    async def action_focus_editor_top(self) -> None:
        editor = self._tabs().current_editor
        if editor is None:
            return
        editor.focus()
        editor.move_cursor((0, 0))

    async def action_focus_editor_bottom(self) -> None:
        editor = self._tabs().current_editor
        if editor is None:
            return
        editor.focus()
        editor.move_cursor(editor.document.end)

    async def action_new_tab(self) -> None:
        self._tabs().new_tab()

    async def action_close_tab(self) -> None:
        self._tabs().close_current()

    async def action_command_palette(self) -> None:  # type: ignore[override]
        # Textual supports async actions at runtime; its stubs only declare
        # the sync signature. Mypy override-suppress is intentional.
        commands = [*BUILTIN_COMMANDS, *self.state.plugins.all_commands()]

        def _on_pick(result: Command | None) -> None:
            if result is None:
                return
            ctx = PluginContext(
                plugin_id="builtin",
                event_bus=self.state.bus,
                registry=self.state.plugins,
            )
            task = asyncio.ensure_future(result.handler(ctx))
            self._palette_task = task

            def _report(done: asyncio.Task[None]) -> None:
                if done.cancelled():
                    return
                exc = done.exception()
                if exc is not None:
                    logger.exception("command_handler_failed", exc_info=exc)
                    self._status().message = f"[red]command failed: {exc}[/]"

            task.add_done_callback(_report)

        await self.push_screen(CommandPaletteScreen(commands), _on_pick)

    async def action_help(self) -> None:
        await self.push_screen(HelpModal())

    async def action_show_history(self) -> None:
        if self.state.history is None:
            self._status().message = "[yellow]history not opened[/]"
            return
        entries = await self.state.history.recent(limit=50)

        def _on_pick(picked: HistoryEntry | None) -> None:
            if picked is None:
                return
            editor = self._tabs().current_editor
            if editor is None:
                self._tabs().new_tab(picked.sql)
            else:
                editor.text = picked.sql

        await self.push_screen(HistoryModal(entries), _on_pick)

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
