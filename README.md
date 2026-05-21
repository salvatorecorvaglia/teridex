# Teridex

> A modern, terminal-native database IDE. Keyboard-first, async, pluggable.

Teridex is a TUI database client rebuilt around a clean async core and a plugin-first architecture.

## Features

- **Fast** — Textual + Rich, virtualized result tables, streamed rows.
- **Keyboard-first** — full command palette, optional Vim bindings.
- **Multi-database** — DuckDB, SQLite, PostgreSQL, MySQL out of the box.
- **Pluggable** — Python entry-point plugins contribute commands, panels, and hooks.
- **Modular** — clean architecture, strong typing (`mypy --strict`), SOLID layering.

## Quick start

```bash
git clone https://github.com/<you>/teridex.git
cd teridex
./scripts/dev.sh

# Launch the TUI
uv run teridex tui --dsn duckdb:///:memory:

# One-shot query, rendered as a Rich table
uv run teridex run --dsn sqlite:///demo.db "SELECT sqlite_version()"

# Discover plugins on the current Python path
uv run teridex plugins list
```

## Supported databases

| Engine     | URL scheme                     | Driver      |
| ---------- | ------------------------------ | ----------- |
| DuckDB     | `duckdb://`                    | `duckdb`    |
| SQLite     | `sqlite://`                    | `aiosqlite` |
| PostgreSQL | `postgres://`, `postgresql://` | `asyncpg`   |
| MySQL      | `mysql://`                     | `asyncmy`   |

## Keybindings (default keymap)

| Key          | Action                      |
| ------------ | --------------------------- |
| `ctrl+enter` | Run query                   |
| `ctrl+c`     | Cancel running query        |
| `ctrl+p`     | Command palette (fuzzy)     |
| `ctrl+r`     | Refresh schema tree         |
| `ctrl+h`     | Query history (last 50)     |
| `ctrl+t`     | New query tab               |
| `ctrl+w`     | Close current tab           |
| `?`          | Help modal (lists bindings) |
| `ctrl+q`     | Quit                        |

Switch to the Vim-flavored keymap by setting `ui.keymap = "vim"` in your config (see below).

## Themes

Two themes ship by default: `monokai` (warm) and `nord` (cool). Set the active theme with `ui.theme` in your config.

## Configuration

Teridex reads (in order) defaults → `~/.config/teridex/config.toml` → environment (`TERIDEX_*`, double-underscore nested, e.g. `TERIDEX_UI__THEME=nord`) → CLI flags.

A working sample lives at [`docs/config.example.toml`](docs/config.example.toml).

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
TERIDEX_PG_DSN=postgres://teridex:teridex@localhost:5432/teridex \
TERIDEX_MYSQL_DSN=mysql://teridex:teridex@localhost:3306/teridex \
TERIDEX_TEST_MARKERS=integration ./scripts/test.sh
```

## Plugins

Plugins are ordinary Python packages that expose a `teridex.plugins` entry point. They can contribute commands (palette + keybindings), dockable panels (left / right / bottom rails), and hook into engine events. See [docs/PLUGINS.md](docs/PLUGINS.md).

## License

MIT — see [LICENSE](LICENSE).
