"""Typer-powered Teridex CLI.

Commands:
    teridex tui --dsn <url>         launch the TUI
    teridex run --dsn <url> "<sql>" one-shot query, prints results as a Rich table
    teridex connect --dsn <url>     connection sanity check
    teridex plugins list            list discovered plugins
    teridex version                 print version + supported drivers

``--dsn`` reads ``TERIDEX_DSN`` from the environment when omitted.
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from enum import StrEnum
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from teridex_adapters import create_adapter_for_dsn, default_registry
from teridex_core.config import load_config
from teridex_core.errors import (
    QueryCancelledError,
    QueryError,
    QueryTimeoutError,
    TeridexError,
)
from teridex_core.events import EventBus
from teridex_core.logging import clear_context, configure_logging, get_logger
from teridex_core.models.connection import Dsn
from teridex_engine.executor import QueryExecutor

logger = get_logger(__name__)
console = Console()


class OutputFormat(StrEnum):
    TABLE = "table"
    CSV = "csv"
    JSON = "json"


def _render(fmt: OutputFormat, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
    """Write *rows* to stdout in the requested format."""
    if fmt is OutputFormat.CSV:
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
        return
    if fmt is OutputFormat.JSON:
        payload = [dict(zip(columns, row, strict=False)) for row in rows]
        # ``default=str`` so dates, Decimals and UUIDs serialize instead of
        # aborting the whole output on the last row.
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    if not columns:
        return
    table = Table(show_lines=False, highlight=True)
    for name in columns:
        table.add_column(escape(name), overflow="fold")
    for row in rows:
        table.add_row(*(escape(str(v)) if v is not None else "[dim]NULL[/]" for v in row))
    console.print(table)


app = typer.Typer(
    name="teridex",
    help="A terminal-first database workspace for modern engineers",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
plugins_app = typer.Typer(help="Plugin management.")
app.add_typer(plugins_app, name="plugins")


@app.callback()
def _root(
    log_level: Annotated[
        str | None, typer.Option("--log-level", help="Log level.", envvar="TERIDEX_LOG_LEVEL")
    ] = None,
) -> None:
    level = log_level or "WARNING"
    configure_logging(level=level)


@app.command()
def version() -> None:
    """Print Teridex version and discovered adapter drivers."""
    from teridex_core import __version__  # noqa: PLC0415 - keep CLI startup fast

    console.print(f"[bold cyan]teridex[/] {__version__}")
    console.print(f"adapters: {', '.join(default_registry().names()) or '[none]'}")


@app.command()
def connect(
    dsn: Annotated[
        str,
        typer.Option(
            "--dsn",
            envvar="TERIDEX_DSN",
            help="Database URL, e.g. duckdb:///:memory:",
        ),
    ],
) -> None:
    """Open a connection to verify the DSN is reachable."""

    async def _go() -> int:
        try:
            parsed = Dsn.parse(dsn)
            adapter = create_adapter_for_dsn(parsed)
            await adapter.connect(parsed)
            try:
                ok = await adapter.ping()
            finally:
                await adapter.close()
        except Exception as exc:
            console.print(f"[bold red]ERROR[/] {escape(str(exc))}")
            return 1
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
    dsn: Annotated[str, typer.Option("--dsn", envvar="TERIDEX_DSN", help="Database URL.")],
    limit: Annotated[int, typer.Option("--limit", min=1, help="Max rows to print.")] = 200,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            min=0,
            help="Abort the query after this many seconds. 0 disables the timeout.",
        ),
    ] = 60.0,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            "-f",
            help="Output format. 'csv' and 'json' are machine-readable (no styling).",
        ),
    ] = OutputFormat.TABLE,
) -> None:
    """Execute one query and print its results.

    ``--format csv`` / ``--format json`` write plain data to stdout so the
    results can be piped into other tools; the row-count summary goes to
    stderr so it never contaminates them.
    """

    async def _go() -> int:
        try:
            parsed = Dsn.parse(dsn)
            adapter = create_adapter_for_dsn(parsed)
            await adapter.connect(parsed)
        except Exception as exc:
            console.print(f"[bold red]CONNECTION ERROR[/] {escape(str(exc))}")
            return 1
        bus = EventBus()
        try:
            executor = QueryExecutor(adapter, bus)
            run_handle = await executor.run(sql, timeout=timeout)
            columns: list[str] = []
            rows: list[tuple[Any, ...]] = []
            try:
                async for batch in run_handle.rows:
                    if not columns and batch.columns:
                        columns = [c.name for c in batch.columns]
                    for row in batch.rows:
                        if len(rows) >= limit:
                            break
                        rows.append(row)
                    if len(rows) >= limit:
                        break
            finally:
                # Release the adapter's cursor/transaction when --limit cut the
                # stream short, rather than leaving it to the garbage collector.
                await run_handle.aclose()

            _render(output, columns, rows)
            summary = f"{run_handle.rows_emitted} row(s) in {run_handle.duration_ms or 0:.1f} ms"
            if output is OutputFormat.TABLE:
                console.print(f"[dim]{summary}[/]")
            else:
                # stderr: stdout belongs to the data being piped.
                Console(stderr=True).print(f"[dim]{summary}[/]")
            return 0
        except QueryTimeoutError as exc:
            console.print(f"[bold red]TIMEOUT[/] {escape(str(exc))}")
            return 1
        except QueryCancelledError:
            console.print("[yellow]query cancelled[/]")
            return 1
        except (QueryError, TeridexError) as exc:
            console.print(f"[bold red]QUERY ERROR[/] {escape(str(exc))}")
            return 1
        except Exception as exc:
            logger.exception("cli_run_unexpected_error")
            console.print(f"[bold red]ERROR[/] {escape(str(exc))}")
            return 1
        finally:
            clear_context()
            await bus.close()
            await adapter.close()

    raise typer.Exit(code=asyncio.run(_go()))


@app.command()
def tui(
    ctx: typer.Context,
    dsn: Annotated[
        str,
        typer.Option("--dsn", envvar="TERIDEX_DSN", help="Initial DSN to connect to."),
    ] = "",
    config_path: Annotated[str, typer.Option("--config", help="Path to config TOML.")] = "",
) -> None:
    """Launch the Teridex TUI."""
    # Lazy imports — keep `teridex version` and `teridex run` fast by not
    # importing Textual unless we actually launch the TUI.
    from pathlib import Path  # noqa: PLC0415

    from teridex_tui.app import TeridexApp  # noqa: PLC0415

    cli_log_level = ctx.parent.params.get("log_level") if ctx.parent else None
    overrides = {}
    if cli_log_level is not None:
        overrides["logging"] = {"level": cli_log_level}

    try:
        cfg = load_config(Path(config_path) if config_path else None, **overrides)
        initial_dsn = Dsn.parse(dsn) if dsn else None
    except Exception as exc:
        console.print(f"[bold red]ERROR[/] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    # Ensure the terminal advertises truecolor support so Textual renders
    # the theme's hex colours correctly.  In some environments (IDE embedded
    # terminals, subprocesses, screen sessions) COLORTERM / TERM may be
    # unset, which causes Textual to degrade to basic 16-colour mode where
    # foreground and background can collapse to the same shade.
    import os  # noqa: PLC0415

    os.environ.setdefault("COLORTERM", "truecolor")
    os.environ.setdefault("TERM", "xterm-256color")

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
