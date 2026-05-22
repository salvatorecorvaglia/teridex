"""CLI surface tests — DSN flag consistency, env var, and exit codes."""

from __future__ import annotations

from typer.testing import CliRunner

from teridex_cli.main import app

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
    result = runner.invoke(
        app, ["run", "--dsn", "not-a-real-scheme://x", "SELECT 1"]
    )
    assert result.exit_code != 0
    assert "ERROR" in result.stdout


def test_run_executes_query_and_prints_rows() -> None:
    result = runner.invoke(
        app,
        ["run", "--dsn", "duckdb:///:memory:", "SELECT 42 AS answer"],
    )
    assert result.exit_code == 0
    assert "42" in result.stdout
    assert "answer" in result.stdout
