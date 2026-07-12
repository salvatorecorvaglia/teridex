# Teridex 📟

**A terminal-native database IDE. Keyboard-first, async, pluggable.**

Teridex is a TUI database client built on a clean async core and a plugin-first architecture. It combines a rich query editor, lazy schema browser, virtualized result tables, and a fuzzy command palette — all inside your terminal.

---

## ✨ Key Features

*   **⚡ Asynchronous Execution**: Multi-threaded, fully cancellable database queries. Long-running queries won't block the TUI layout or cursor.
*   **⌨️ Keyboard-First Design**: Optimized for hands-on-keyboard speed. Support for both standard and Vim-style keybindings (press `?` in the TUI to toggle the active keybindings list).
*   **🔌 Pluggable Architecture**: Easily write plugins to add custom panels, new commands to the palette, or listen to event hooks.
*   **🗃️ Built-in Database Drivers**: First-class support for **DuckDB**, **SQLite**, **PostgreSQL**, and **MySQL**.
*   **📝 Rich Workspace Layout**:
    *   **Live Schema Tree**: Real-time introspection of schemas, tables, columns, indexes, and foreign keys (with full index and foreign key support implemented for DuckDB, PostgreSQL, MySQL, and SQLite).
    *   **Multi-Tab SQL Editor**: Edit multiple queries side-by-side with SQL syntax highlighting.
    *   **Interactive Results Table**: Search, filter, and scroll through large result sets cleanly using pagination/batch loading. Features a dynamic row display limit configuration dialog (set row limit on the fly via the command palette).
    *   **Command Palette**: Quick actions, screen switching, and plugin commands.
*   **⚙️ Configuration Layer**: Customize the look and feel (including Monokai and Nord themes) and define saved connections.

---

## 📐 Package Architecture & Layering

Teridex follows a clean, layered architecture with strict dependency boundaries:

```mermaid
graph TD
    core["teridex_core (Pure Domain)"]
    adapters["teridex_adapters (DB Drivers)"]
    plugins["teridex_plugins (Plugin API)"]
    engine["teridex_engine (Orchestration)"]
    tui["teridex_tui (Textual TUI)"]
    cli["teridex_cli (Typer CLI)"]

    adapters --> core
    plugins --> core
    engine --> adapters
    engine --> plugins
    tui --> engine
    cli --> engine
```

> [!IMPORTANT]
> **Dependency Isolation**: Inner packages must never depend on outer packages. Specifically, `teridex_core` has no dependencies on any other internal package. These boundaries are strictly verified via `mypy --strict`.

---

## 🚀 Getting Started

### Prerequisites

*   **Python >= 3.13**
*   The [**`uv`**](https://docs.astral.sh/uv/) package manager (recommended) or standard `pip`.

### Installation

Install Teridex using `uv` or standard Python package managers:

```bash
# Install core package
pip install teridex

# Install with support for all database drivers (Postgres, MySQL, SQLite, DuckDB)
pip install "teridex[all]"

# Install with specific drivers
pip install "teridex[postgres]"
pip install "teridex[duckdb]"
```

Alternatively, clone the repository for local development:

```bash
git clone https://github.com/salvatorecorvaglia/teridex.git
cd teridex
./scripts/dev.sh
```

### Running the TUI

Start the workspace by pointing it to a database DSN (Data Source Name):

```bash
# Open with a temporary in-memory DuckDB
teridex tui --dsn duckdb:///:memory:

# Connect to a local SQLite database file
teridex tui --dsn sqlite:///path/to/database.db

# Connect to a PostgreSQL instance
teridex tui --dsn postgresql://user:password@localhost:5432/mydatabase
```

### One-Shot CLI Execution

Run query statements directly from the command line and view results rendered as a styled table:

```bash
teridex run --dsn duckdb:///:memory: "SELECT 'Hello, Teridex!' AS message"
```

---

## ⚙️ Configuration

Configure Teridex via the config file located at `~/.config/teridex/config.toml`. 

Refer to the [config.example.toml](config.example.toml) file for available options:

```toml
[ui]
theme = "monokai"       # "monokai" (warm) or "nord" (cool)
keymap = "default"      # "default" or "vim"
show_status_bar = true
row_batch_size = 1000   # Rows per batch to fetch from adapters
max_display_rows = 10000 # Max rows held in results grid (0 for unlimited)

[engine]
default_timeout_seconds = 60.0
max_history_entries = 1000
pool_size = 5

[logging]
level = "INFO"

[plugins]
enabled = []            # Specify IDs of plugins to load (empty loader registers all)
disabled = []           # Specify IDs of plugins to exclude

[connections]
# Save connection profiles to reference by name
# local-duckdb = "duckdb:///:memory:"
# local-pg     = "postgres://user:pass@localhost:5432/dbname"
```

### Environment Overrides
You can override configuration keys using environment variables using the structure: `TERIDEX_<SECTION>__<FIELD>`.
For example:
```bash
TERIDEX_UI__THEME=nord teridex tui
```

---

## 🔌 Extensibility: Writing Plugins

Plugins are discovered using Python entry points registered under the `teridex.plugins` group in your package's metadata. 

A plugin needs to implement the [Plugin](src/teridex_core/protocols/plugin.py#L22-L29) protocol.

### 1. Define the Manifest and Hooks

Create a class with a `manifest` property, `on_load`, and `on_unload` methods:

```python
from teridex_plugins import PluginContext, Command, hook
from teridex_core.protocols.plugin import PluginManifest

class MyPlugin:
    manifest = PluginManifest(
        id="custom-notifier",
        name="Custom Notifier",
        version="0.1.0",
        description="Warns users when executing risky SQL queries.",
        requires_teridex=">=0.1.0"
    )

    def on_load(self, ctx: PluginContext) -> None:
        # Register command palette action
        ctx.register_command(
            Command(
                id="notify-hello",
                title="Hello Notifier",
                handler=self.hello_handler,
                default_binding="ctrl+h"
            )
        )
        ctx.logger.info("Custom Notifier plugin successfully loaded!")

    def on_unload(self, ctx: PluginContext) -> None:
        ctx.logger.info("Custom Notifier plugin unloaded.")

    async def hello_handler(self, ctx: PluginContext) -> None:
        ctx.publish(SomeNotificationEvent("Hello from plugin!"))

    @hook("query.before_execute")
    async def warn_on_drop(self, ctx: PluginContext, sql: str) -> None:
        if "drop table" in sql.lower():
            ctx.logger.warning("Risky query detected!", sql=sql)
```

Refer to [api.py](src/teridex_plugins/api.py) and [context.py](src/teridex_plugins/context.py) for the complete plugin-facing API surface.

---

## 🛠️ Extensibility: Custom Database Adapters

Add adapters by subclassing [AbstractAdapter](src/teridex_adapters/base.py#L45-L161):

1. Subclass `AbstractAdapter` and set the driver names and URL schemas.
2. Implement `_do_connect`, `_do_close`, `ping`, `execute`, `stream`, `begin`, and `introspect`.
3. Register your driver class in [registry.py](src/teridex_adapters/registry.py).

> [!TIP]
> All database adapters automatically support asynchronous context manager usage (`async with adapter: ...`) via `AbstractAdapter` to guarantee clean connection teardown.

---

## 🛠️ Local Development & Testing

We provide helper scripts inside the `scripts/` directory to run checks, tests, and formatting easily:

*   **Run All Quality Gates**: `./scripts/check.sh` (Runs linting, typing, formatting, and unit tests).
*   **Format Code**: `./scripts/fmt.sh` (Using Ruff).
*   **Lint & Type Checking**: `./scripts/lint.sh` (Ruff and Mypy strict).
*   **Unit Tests**: `./scripts/test.sh` (Pytest).
*   **Integration Tests**: `TERIDEX_TEST_MARKERS=integration ./scripts/test.sh` (using `testcontainers` if Docker is running).


---

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 🔐 Security

If you discover a security vulnerability, please see our [Security Policy](SECURITY.md).

## 📝 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

---

**Author**: [Salvatore Corvaglia](https://github.com/salvatorecorvaglia)
