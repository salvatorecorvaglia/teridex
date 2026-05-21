# Teridex

> A modern, terminal-native database IDE. Keyboard-first, async, pluggable.

Teridex is a TUI database client rebuilt around a clean async core and a plugin-first architecture.

## Features

- 🚀 **Fast** — Textual + Rich, virtualized result tables, streamed rows.
- ⌨️ **Keyboard-first** — full command palette, optional Vim bindings.
- 🗄️ **Multi-database** — DuckDB, SQLite, PostgreSQL, MySQL out of the box.
- 🔌 **Pluggable** — Python entry-point plugins contribute commands, panels, and hooks.
- 🧩 **Modular** — clean architecture, strong typing (`mypy --strict`), SOLID layering.

## Quick start

```bash
# Install (development)
git clone https://github.com/<you>/teridex.git
cd teridex
./scripts/dev.sh

# Run the TUI
uv run teridex tui --dsn duckdb:///:memory:

# Run a one-shot query
uv run teridex run --dsn sqlite:///demo.db "SELECT sqlite_version()"
```

## Supported databases

| Engine     | URL scheme                     | Driver      |
| ---------- | ------------------------------ | ----------- |
| DuckDB     | `duckdb://`                    | `duckdb`    |
| SQLite     | `sqlite://`                    | `aiosqlite` |
| PostgreSQL | `postgres://`, `postgresql://` | `asyncpg`   |
| MySQL      | `mysql://`                     | `asyncmy`   |

## Project layout

```
apps/        # User-facing entry points (CLI, TUI)
packages/    # Library code (core, adapters, engine, plugins)
tests/       # Unit + integration suites
docker/      # Container image + dev compose
docs/        # Architecture, plugin authoring, contributing
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Development

```bash
./scripts/dev.sh         # uv sync + pre-commit install
./scripts/fmt.sh         # ruff format + autofix
./scripts/lint.sh        # ruff + mypy --strict
./scripts/test.sh        # pytest (excludes integration by default)

# Run integration tests against local Postgres/MySQL
docker compose -f docker/docker-compose.yml up -d
TERIDEX_TEST_MARKERS="integration or not integration" ./scripts/test.sh
```

## Plugins

Plugins are ordinary Python packages exposing a `teridex.plugins` entry point.
See [docs/PLUGINS.md](docs/PLUGINS.md).

## License

MIT — see [LICENSE](LICENSE).
