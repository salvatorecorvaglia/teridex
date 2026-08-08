# Teridex 📟

**Terminal-native, keyboard-first async database IDE**

**Teridex** is a TUI database client built on a clean async core and a plugin-first architecture. It combines a rich query editor, lazy schema browser, virtualized result tables, and a fuzzy command palette — all inside your terminal.

---

## ✨ Features

- **🎹 Keyboard-First Layout**: Fully navigatable using Vim keys or custom layout keymaps.
- **⚡ Asynchronous Execution Engine**: Run queries in the background. Long-running queries will never freeze the UI, and can be cancelled with a single keystroke.
- **🔌 Pluggable Architecture**: Extend functionality with custom panels, commands, and hooks subscribing to runtime event lifecycles.
- **📊 Interactive TUI**: Rich results viewer, schema tree explorer, syntax highlighting, and batch rendering.
- **🛠️ Command Line Interface**: Fast, standalone utilities to connect, test connections, and execute queries directly to standard output.

---

## 🗄️ Supported Databases

Teridex is database-agnostic and loads drivers dynamically via optional extras.

| Database | Extra | Adapter Protocol | Details |
| :--- | :--- | :--- | :--- |
| **DuckDB** | `[duckdb]` | `duckdb` | Direct in-process analytics engine |
| **SQLite** | `[sqlite]` | `aiosqlite` | Async local database access |
| **PostgreSQL** | `[postgres]` | `asyncpg` | Native async driver for Postgres |
| **MySQL** | `[mysql]` | `asyncmy2` | Native async driver for MySQL |
| **All Drivers** | `[all]` | — | Installs all supported drivers |

---

## 🚀 Installation

Teridex requires **Python 3.13 or newer**. It is recommended to install using `pipx` or `uv` to keep the dependencies isolated.

### Using `uv` (Recommended)

```bash
# Install with all database drivers
uv tool install "teridex[all]"

# Install with PostgreSQL and SQLite support only
uv tool install "teridex[postgres,sqlite]"
```

### Using `pipx`

```bash
# Install with DuckDB support
pipx install "teridex[duckdb]"
```

---

## 📖 Quick Start

You can run queries one-shot from the shell or jump into the terminal user interface.

### Running a One-Shot Query

Use the `run` command to execute a single query and render the result as a styled table:

```bash
teridex run --dsn "sqlite:///./my_database.db" "SELECT * FROM users LIMIT 5"
```

### Starting the TUI

Launch the full interactive terminal IDE:

```bash
teridex tui --dsn "postgres://user:pass@localhost:5432/my_db"
```

### Command Reference

```bash
# Display help and options
teridex --help

# Print version and discovered database adapters
teridex version

# Sanity check database connection
teridex connect --dsn "mysql://root:secret@127.0.0.1/test"

# List discovered plugins
teridex plugins list
```

---

## ⚙️ Configuration

Teridex configuration is loaded in layers: **Defaults ➡️ TOML Configuration ➡️ Environment Variables ➡️ CLI Flags**.

The default configuration file is searched at `~/.config/teridex/config.toml`. The configuration file must have secure permissions (e.g., `0600`) if it contains credentials.

Here is an example config file (see [config.example.toml](config.example.toml)):

```toml
[ui]
theme = "monokai"               # Theme: "monokai" (warm) | "nord" (cool)
keymap = "default"              # Keymap: "default" | "vim"
row_batch_size = 1000           # Query result batch loading size
max_display_rows = 10000        # Caps rows stored in results view

[engine]
default_timeout_seconds = 60.0  # Soft limit for query runs
max_history_entries = 1000      # Max CLI query history entries
pool_size = 5                   # Connection pool size

[logging]
level = "INFO"                  # Log level: DEBUG | INFO | WARNING | ERROR

[plugins]
enabled = []                    # Allowlist (empty loads all discovered)
disabled = []                   # Blocklist
```

### Environment Overrides

Any configuration value can be overridden via environment variables using the pattern `TERIDEX_<SECTION>__<FIELD>`.

Examples:
```bash
# Override the UI theme
export TERIDEX_UI__THEME="nord"

# Override keymap to vim
export TERIDEX_UI__KEYMAP="vim"
```

---

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📜 Changelog

Detailed release history and version changes can be found in [CHANGELOG.md](CHANGELOG.md).

## 🔐 Security

If you discover a security vulnerability, please see our [Security Policy](SECURITY.md).

## 📝 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

---

**Author**: [Salvatore Corvaglia](https://github.com/salvatorecorvaglia)