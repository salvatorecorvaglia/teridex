"""Typer-powered Teridex CLI.

Commands:
    teridex tui --dsn <url>         launch the TUI
    teridex run --dsn <url> "<sql>" one-shot query, prints results as a Rich table
    teridex connect <url>           connection sanity check
    teridex plugins list            list discovered plugins
    teridex version                 print version + supported drivers
"""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from teridex_adapters import create_adapter_for_dsn, default_registry
from teridex_core.config import load_config
from teridex_core.events import EventBus
from teridex_core.logging import configure_logging, get_logger
from teridex_core.models.connection import Dsn
from teridex_engine.executor import QueryExecutor

logger = get_logger(__name__)
console = Console()

app = typer.Typer(
    name="teridex",
    help="Teridex — terminal-native database IDE.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
plugins_app = typer.Typer(help="Plugin management.")
app.add_typer(plugins_app, name="plugins")


@app.callback()
def _root(
    log_level: Annotated[
        str, typer.Option("--log-level", help="Log level.", envvar="TERIDEX_LOG_LEVEL")
    ] = "WARNING",
) -> None:
    configure_logging(level=log_level)


@app.command()
def version() -> None:
    """Print Teridex version and discovered adapter drivers."""
    from teridex_core import __version__  # noqa: PLC0415 - keep CLI startup fast

    console.print(f"[bold cyan]teridex[/] {__version__}")
    console.print(f"adapters: {', '.join(default_registry().names()) or '[none]'}")


@app.command()
def connect(
    dsn: Annotated[str, typer.Argument(help="Database URL, e.g. duckdb:///:memory:")],
) -> None:
    """Open a connection to verify the DSN is reachable."""

    async def _go() -> int:
        parsed = Dsn.parse(dsn)
        adapter = create_adapter_for_dsn(parsed)
        await adapter.connect(parsed)
        ok = await adapter.ping()
        await adapter.close()
        console.print(
            f"[bold green]OK[/] connected to {parsed.scheme}://…/{parsed.database or ''}"
            if ok
            else "[bold red]FAIL[/] ping failed"
        )
        return 0 if ok else 1

    raise typer.Exit(code=asyncio.run(_go()))


@app.command("run")
def run_query(
    sql: Annotated[str, typer.Argument(help="SQL to execute.")],
    dsn: Annotated[str, typer.Option("--dsn", help="Database URL.")],
    limit: Annotated[int, typer.Option("--limit", min=1, help="Max rows to print.")] = 200,
) -> None:
    """Execute one query and render results as a Rich table."""

    async def _go() -> int:
        parsed = Dsn.parse(dsn)
        adapter = create_adapter_for_dsn(parsed)
        await adapter.connect(parsed)
        bus = EventBus()
        try:
            executor = QueryExecutor(adapter, bus)
            run_handle = await executor.run(sql)
            table: Table | None = None
            shown = 0
            async for batch in run_handle.rows:
                if table is None and batch.columns:
                    table = Table(show_lines=False, highlight=True)
                    for col in batch.columns:
                        table.add_column(col.name, overflow="fold")
                if table is not None:
                    for row in batch.rows:
                        if shown >= limit:
                            break
                        table.add_row(*(str(v) if v is not None else "[dim]NULL[/]" for v in row))
                        shown += 1
                if shown >= limit:
                    break
            if table is not None:
                console.print(table)
            console.print(
                f"[dim]{run_handle.rows_emitted} row(s) in {run_handle.duration_ms or 0:.1f} ms[/]"
            )
            return 0
        finally:
            await bus.close()
            await adapter.close()

    raise typer.Exit(code=asyncio.run(_go()))


@app.command()
def tui(
    dsn: Annotated[str, typer.Option("--dsn", help="Initial DSN to connect to.")] = "",
    config_path: Annotated[str, typer.Option("--config", help="Path to config TOML.")] = "",
) -> None:
    """Launch the Teridex TUI."""
    # Lazy imports — keep `teridex version` and `teridex run` fast by not
    # importing Textual unless we actually launch the TUI.
    from pathlib import Path  # noqa: PLC0415

    from teridex_tui.app import TeridexApp  # noqa: PLC0415

    cfg = load_config(Path(config_path) if config_path else None)
    initial_dsn = Dsn.parse(dsn) if dsn else None
    TeridexApp(config=cfg, initial_dsn=initial_dsn).run()


@plugins_app.command("list")
def plugins_list() -> None:
    """List discovered Teridex plugins."""
    # Lazy: only pulled in for `teridex plugins list`.
    from teridex_plugins.loader import PluginLoader  # noqa: PLC0415
    from teridex_plugins.registry import PluginRegistry  # noqa: PLC0415

    bus = EventBus()
    loader = PluginLoader(PluginRegistry(), bus)
    eps = loader.discover()
    if not eps:
        console.print("[yellow]no plugins found[/]")
        return
    table = Table("name", "module", title="Discovered plugins")
    for ep in eps:
        table.add_row(ep.name, ep.value)
    console.print(table)


def main() -> None:  # entry-point shim
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
