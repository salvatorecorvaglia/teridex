# Teridex

> A modern, terminal-native database IDE. Keyboard-first, async, pluggable.

Teridex is a TUI database client built on a clean async core and a plugin-first architecture. It combines a rich query editor, lazy schema browser, virtualized result tables, and a fuzzy command palette — all inside your terminal.

---

## Features

- **Fast** — Textual + Rich, virtualized result tables, streamed row batches.
- **Keyboard-first** — full command palette, optional Vim keybindings.
- **Multi-database** — DuckDB, SQLite, PostgreSQL, MySQL out of the box.
- **Pluggable** — Python entry-point plugins contribute commands, panels, and event hooks.
- **Modular** — clean-architecture layering, strict typing (`mypy --strict`), SOLID.
- **Connection pool** — bounded, lazy pool for concurrent query execution.
- **Query history** — persistent local history store with recall from the TUI.
- **Export** — copy individual cells or export full result sets to CSV.

---

## Requirements

- Python **≥ 3.13**
- [`uv`](https://docs.astral.sh/uv/) package manager

---

## Installation

### Homebrew (macOS / Linux)

```bash
brew tap salvatorecorvaglia/teridex
brew install teridex
```

### From source

```bash
git clone https://github.com/salvatorecorvaglia/teridex.git
cd teridex
./scripts/dev.sh          # uv sync + pre-commit install
```

---

## Quick start

```bash

# Launch the TUI
uv run teridex tui --dsn duckdb:///:memory:

# One-shot query, rendered as a Rich table
uv run teridex run --dsn sqlite:///demo.db "SELECT sqlite_version()"

# Verify a connection is reachable
uv run teridex connect --dsn postgres://user:pass@localhost:5432/mydb

# Print version and discovered adapter drivers
uv run teridex version

# Discover plugins on the current Python path
uv run teridex plugins list
```

`--dsn` can also be set via the `TERIDEX_DSN` environment variable.

---

## Supported databases

| Engine     | URL scheme                     | Driver      |
| ---------- | ------------------------------ | ----------- |
| DuckDB     | `duckdb://`                    | `duckdb`    |
| SQLite     | `sqlite://`                    | `aiosqlite` |
| PostgreSQL | `postgres://`, `postgresql://` | `asyncpg`   |
| MySQL      | `mysql://`                     | `asyncmy`   |

---

## Keybindings (default keymap)

| Key          | Action                      |
| ------------ | --------------------------- |
| `ctrl+enter` | Run query                   |
| `ctrl+j`     | Run query (alternate)       |
| `ctrl+c`     | Cancel running query        |
| `ctrl+p`     | Command palette (fuzzy)     |
| `ctrl+r`     | Refresh schema tree         |
| `ctrl+h`     | Query history (last 50)     |
| `ctrl+t`     | New query tab               |
| `ctrl+w`     | Close current tab           |
| `ctrl+y`     | Copy cell to clipboard      |
| `ctrl+e`     | Export results to CSV       |
| `?`          | Help modal (lists bindings) |
| `ctrl+q`     | Quit                        |

### Vim keymap

Set `ui.keymap = "vim"` in your config to add these extra bindings on top of the defaults:

| Key   | Action           |
| ----- | ---------------- |
| `:`   | Command palette  |
| `g g` | Top of editor    |
| `G`   | Bottom of editor |

---

## Themes

Two themes ship by default: **monokai** (warm) and **nord** (cool). Set the active theme with `ui.theme` in your config.

---

## Configuration

Teridex reads (in order) defaults → `~/.config/teridex/config.toml` → environment (`TERIDEX_*`, double-underscore nested, e.g. `TERIDEX_UI__THEME=nord`) → CLI flags.

A working sample lives at [`config.example.toml`](config.example.toml).

### Settings reference

| Setting Key | Type | Default Value | Description / Validations |
| :--- | :--- | :--- | :--- |
| `ui.theme` | `string` | `"monokai"` | Theme name. Built-ins: `"monokai"` (warm) \| `"nord"` (cool). |
| `ui.keymap` | `string` | `"default"` | Keymap bindings mode. `"default"` or `"vim"`. |
| `ui.show_status_bar` | `boolean` | `true` | Toggle visibility of the bottom status bar. |
| `ui.row_batch_size` | `integer` | `1000` | Number of rows fetched per batch from adapters. Range: `10` to `100,000`. |
| `ui.max_display_rows` | `integer` | `10,000` | Max rows held in results grid. Capped for memory safety (`0` for unlimited). |
| `engine.default_timeout_seconds` | `float` | `60.0` | Default timeout for query execution in seconds. Must be `> 0`. |
| `engine.max_history_entries` | `integer` | `1000` | Bounded size of local query-history database. Must be `>= 10`. |
| `engine.pool_size` | `integer` | `5` | Size of concurrent database connection pool. Range: `1` to `64`. |
| `logging.level` | `string` | `"INFO"` | Logging filter level: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`. |
| `logging.json_lines` | `boolean \| null` | `null` | Emit logs as single JSON lines. `null` auto-detects based on TTY. |
| `plugins.enabled` | `list[str]` | `[]` | List of plugins allowed to load. Empty loads all discovered. |
| `plugins.disabled` | `list[str]` | `[]` | List of plugins to explicitly block. |
| `connections` | `object` | `{}` | Saved connection DSNs mapped by connection name. |

---

## 🛡️ Resource & Safety Limits

To guarantee terminal responsiveness, protect database servers from connection exhaustion, and prevent memory issues, Teridex enforces several safety boundaries:

- **Query Timeouts**: Runaway queries are automatically cancelled after a soft limit of `60.0` seconds (`engine.default_timeout_seconds`), protecting the database and client from resource starvation.
- **Connection Pools**: Database connections are strictly managed using a bounded, lazy pool capped at `5` connections (`engine.pool_size`) by default. This protects backend servers from database connection exhaustion.
- **Row Stream Batching**: Rows are fetched asynchronously and rendered into the `DataTable` in chunks of `1000` (`ui.row_batch_size`) to maintain smooth UI frame rates and zero typing lag.
- **TUI Memory Guard**: To prevent terminal rendering freezes, the results grid is capped at displaying `10,000` rows (`ui.max_display_rows`) by default.
- **Query History**: The local query history store retains a maximum of `1000` entries (`engine.max_history_entries`) to prevent infinite growth.

---

## Project layout

```
apps/
  teridex-cli/       Typer-based CLI (tui, run, connect, version, plugins)
  teridex-tui/       Textual TUI app, widgets, screens, themes, keymaps

packages/
  teridex-core/      Pure domain: Pydantic models, errors, DI container,
                     event bus, config, structured logging, protocols
  teridex-adapters/  Concrete DB drivers behind a unified DatabaseAdapter
                     protocol (one file per database)
  teridex-engine/    Orchestration: QueryExecutor, ConnectionPool,
                     Introspector, QueryHistory
  teridex-plugins/   Public plugin API (Command, Panel, hook), PluginContext,
                     entry-point loader

tests/               Unit + integration suites (adapters, core, engine,
                     cli, tui, plugins)
docker/              Dockerfile + dev compose (Postgres + MySQL)
scripts/             dev.sh, fmt.sh, lint.sh, test.sh, check.sh
```

---

## Development

```bash
./scripts/dev.sh         # uv sync + pre-commit install
./scripts/fmt.sh         # ruff format + autofix
./scripts/lint.sh        # ruff + mypy --strict
./scripts/test.sh        # pytest (excludes integration by default)
./scripts/check.sh       # lint + test in one shot (extra args → pytest)

# Run integration tests against local Postgres/MySQL
docker compose -f docker/docker-compose.yml up -d
TERIDEX_PG_DSN=postgres://teridex:teridex@localhost:5432/teridex \
TERIDEX_MYSQL_DSN=mysql://teridex:teridex@localhost:3306/teridex \
TERIDEX_TEST_MARKERS=integration ./scripts/test.sh
```

---

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 🔐 Security

If you discover a security vulnerability, please see our [Security Policy](SECURITY.md).

## 📝 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

---

**Author**: [Salvatore Corvaglia](https://github.com/salvatorecorvaglia)
