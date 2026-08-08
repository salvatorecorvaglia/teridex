"""CLI surface tests — DSN flag consistency, env var, and exit codes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from teridex_cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_version_runs() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "teridex" in result.stdout.lower()


def test_connect_requires_dsn_flag() -> None:
    # Positional DSN must NOT be accepted — that's the old surface.
    result = runner.invoke(app, ["connect", "duckdb:///:memory:"])
    assert result.exit_code != 0


def test_connect_with_dsn_flag_succeeds() -> None:
    result = runner.invoke(app, ["connect", "--dsn", "duckdb:///:memory:"])
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_connect_with_envvar_succeeds() -> None:
    result = runner.invoke(
        app,
        ["connect"],
        env={"TERIDEX_DSN": "duckdb:///:memory:"},
    )
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_run_with_bad_dsn_exits_nonzero() -> None:
    result = runner.invoke(app, ["run", "--dsn", "not-a-real-scheme://x", "SELECT 1"])
    assert result.exit_code != 0
    assert "ERROR" in result.stdout


def test_connect_with_bad_dsn_exits_cleanly() -> None:
    # A bad DSN must produce a clean error message, not a raw traceback.
    result = runner.invoke(app, ["connect", "--dsn", "not-a-real-scheme://x"])
    assert result.exit_code != 0
    assert "ERROR" in result.stdout
    assert "Traceback" not in result.stdout


def test_tui_with_malformed_config_exits_cleanly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("this is = not valid = toml\n")
    result = runner.invoke(app, ["tui", "--config", str(bad)])
    assert result.exit_code != 0
    assert "ERROR" in result.stdout
    assert "Traceback" not in result.stdout


def test_run_executes_query_and_prints_rows() -> None:
    result = runner.invoke(
        app,
        ["run", "--dsn", "duckdb:///:memory:", "SELECT 42 AS answer"],
    )
    assert result.exit_code == 0
    assert "42" in result.stdout
    assert "answer" in result.stdout


def test_run_defaults_to_a_rendered_table() -> None:
    result = runner.invoke(app, ["run", "--dsn", "duckdb:///:memory:", "SELECT 1 AS n"])
    assert result.exit_code == 0
    assert "n" in result.stdout
    assert "row(s)" in result.stdout


def test_run_csv_writes_plain_data() -> None:
    result = runner.invoke(
        app,
        ["run", "--dsn", "duckdb:///:memory:", "SELECT 1 AS n, 'a,b' AS txt", "--format", "csv"],
    )
    assert result.exit_code == 0
    # Quoted because the value contains the delimiter — and no table borders.
    assert 'n,txt\n1,"a,b"' in result.stdout
    assert "┏" not in result.stdout


def test_run_json_writes_parsable_output() -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dsn",
            "duckdb:///:memory:",
            "SELECT 1 AS n, NULL AS empty",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"n": 1, "empty": None}]


def test_run_renders_markup_in_values_literally() -> None:
    """A value containing Rich markup must not restyle — or crash — the table."""
    result = runner.invoke(app, ["run", "--dsn", "duckdb:///:memory:", "SELECT '[bold]x[/]' AS v"])
    assert result.exit_code == 0
    assert "[bold]x[/]" in result.stdout


def test_run_limit_caps_printed_rows() -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--dsn",
            "duckdb:///:memory:",
            "SELECT * FROM range(100) t(i)",
            "--limit",
            "3",
            "--format",
            "csv",
        ],
    )
    assert result.exit_code == 0
    data_lines = [ln for ln in result.stdout.strip().splitlines() if ln]
    assert len(data_lines) == 4  # header + 3 rows


def test_plugins_list_runs() -> None:
    result = runner.invoke(app, ["plugins", "list"])
    assert result.exit_code == 0
