# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.0] - 2026-09-05

### Changed

- **Breaking (keybinding):** "Show history" moved from `Ctrl+H` to `Ctrl+G`. Terminals send `Ctrl+H` for Backspace (it is ASCII BS), so an app-level binding there fired on an ordinary editing keystroke.
- **Breaking (DSN):** PostgreSQL DSN query parameters are now validated against an allowlist (`sslmode`, `sslrootcert`, `sslcert`, `sslkey`, `application_name`, `connect_timeout`, `target_session_attrs`), matching the DuckDB, MySQL, and SQLite adapters. Previously the query string was passed straight to libpq, so a DSN could reach any server setting (`options=-c ...`). An unrecognized parameter is now refused by name at connect time.
- The status bar footer now derives its keys from the active keymap rather than restating them, so a binding change can no longer leave the footer advertising a key that does nothing.
- The action bar's row-count label reads "Display cap" instead of "Limit", which read as a SQL `LIMIT` clause rather than the size of the results grid.
- `RowLimitModal` and `ConnectionScreen` report invalid input inline and stay open, instead of rejecting it with a silent `return` that made Enter look like a dead key. `ConnectionScreen` also parses the DSN before dismissing, so a typo is corrected in the field that holds it.
- `HelpModal` now extends `BaseModal` like every other modal, and notes that `Ctrl+C` cancels the running query rather than quitting (`Ctrl+Q` quits).
- The query-history store location is configurable via `engine.history_path`; it was the only path in the application still hardcoded.
- The release workflow now runs the full CI gate (ruff, mypy, and the test matrix) before publishing. Tag validation alone let a tagged commit reach PyPI without a single test having run against it. Workflow permissions are scoped to the publishing job.
- Raised the offline coverage gate from 73% to 79%.

### Fixed

- **Resource leak:** the SQLite and MySQL adapters leaked one open driver cursor and one `asyncio.Event` per statement that returns no columns (every `INSERT`/`UPDATE`/`CREATE`). `stream()`'s no-columns early return sat above the `try/finally` that releases them, so the leak was unbounded over the life of a pooled connection.
- **Resource leak:** `QueryRun.aclose()` closed only the executor's wrapper, leaving the adapter's own generator suspended at its `yield` — so the driver cursor, and on PostgreSQL the transaction wrapping the server-side cursor, outlived the run and survived the connection's return to the pool. Both documented early-exit paths (the TUI's display cap and the CLI's `--limit`) were affected. `aclose()` is now idempotent.
- **Data correctness:** the MySQL adapter typed every `TINYINT` column — and therefore every `BOOLEAN`, which MySQL stores as `TINYINT(1)` — as a string. The driver aliases `FIELD_TYPE.CHAR` onto `FIELD_TYPE.TINY` (both `1`), and the `CHAR` entry silently overwrote the `TINY` one. Native type names are no longer derived from `vars(FIELD_TYPE)`, whose iteration order decided which of two aliased names won.
- A failed `_do_connect` no longer strands the driver connection. Every adapter opens its connection and *then* runs a follow-up statement (PRAGMAs, `pg_backend_pid()`, `CONNECTION_ID()`); because `close()` is a no-op until `connect()` completes, a failure in that second half leaked the connection and, for aiosqlite, its worker thread.
- `Introspector` no longer answers a request for a full schema snapshot with a cached lazy one, which held no columns and so silently returned an empty schema.
- Plugin bottom rails are now laid out: the app applied a `with-bottom` class that the stylesheet defined no rules for, leaving the rail an unplaced third child of a two-column grid.
- CSV export (both `teridex run --format csv` and the TUI exporter) now defuses values a spreadsheet would evaluate as formulas.

### Removed

- Dropped the unused `idx_history_started` index: both readers order by `id`, so it was never used for a lookup and only cost a write per insert. Existing history databases drop it on next open.

### Chore

- Factored the duplicated "already cancelled" stream in the SQLite and MySQL adapters into a shared `_CancelledStream`, removing an always-true `if` that guarded an unreachable `yield`.
- Removed a no-op `except Exception: raise` in `teridex_engine.transaction`, a duplicate `Dsn` import, and a redundant function-local `contextlib` import.
- Hoisted `datetime`/`decimal`/`uuid` imports in `_typeinfer` to module scope; they were re-imported per column, per result set.
- `SchemaTree` posts an `IntrospectionFailed` message instead of reaching into the app's private `_status` method.
- `TeridexApp.__init__` no longer touches the filesystem; log setup moved to `on_mount` and falls back to stderr when `$HOME` is not writable.

## [1.2.0] - 2026-08-25

### Added

- Added a "Show help" builtin command to the TUI command palette.
- Added `resources/teridex.svg` project logo.

### Changed

- Centralized adapter connection and error handling in `AbstractAdapter` (`_require_conn`, `_wrap_driver_error`), standardizing "not connected" errors and driver-error translation into `QueryError`/`QueryCancelledError` across the DuckDB, MySQL, PostgreSQL, and SQLite adapters.
- Added a `connected` property to the `DatabaseAdapter` protocol.
- Environment variable configuration overrides now process `os.environ` in sorted order, so a nested field override (e.g. `TERIDEX_ENGINE__POOL_SIZE`) deterministically wins over a same-section scalar override (e.g. `TERIDEX_ENGINE`), regardless of the OS/shell's environment iteration order.
- Command palette default keybindings are now derived from the active keymap's bindings instead of separately hardcoded literals, preventing displayed hints from drifting out of sync with the real keymap.
- Updated CI and release GitHub Actions workflows.

### Fixed

- `PluginLoader` now raises a structured `PluginLoadError` instead of an unhandled exception when a plugin's `.manifest` property access itself raises.

### Chore

- Pinned `ruff` dev dependency to `==0.16.4` (previously `>=0.15`).

## [1.1.0] - 2026-08-12

### Added

- Introduced `TuiSession` model for managing active database connection state and query execution sessions in the TUI.
- Added adapter helper modules (`_params.py` and `_typeinfer.py`) to standardize parameter bindings and type inference across DuckDB, MySQL, PostgreSQL, and SQLite adapters.
- Expanded database schema introspection for table types, foreign keys, and indexes across all database adapters.
- Added comprehensive test suites including adapter conformance tests (`test_conformance_*`), bulk introspection tests (`test_bulk_introspection.py`), DSN parameter parsing tests (`test_dsn_params.py`), TUI markup escaping tests (`test_markup_escaping.py`), and TUI connection pool integration tests (`test_pool_in_app.py`).
- Added `tests/scripts/test-integration.sh` to run full integration test suites against live Docker containers.

### Changed

- Refactored `DuckDBAdapter`, `MySQLAdapter`, `PostgresAdapter`, and `SQLiteAdapter` for consistent query execution, connection recycling, improved cancellation support, and robust error propagation.
- Enhanced `QueryExecutor` with explicit query lifecycle transitions, improved row limit enforcement, and detailed error logging.
- Standardized TUI modal screens (`ConnectionScreen`, `CommandPaletteScreen`, `HistoryScreen`, `RowLimitModal`) using a unified screen base (`_base.py`).
- Refined multi-stage Dockerfile (`docker/Dockerfile`) to use non-editable installs (`uv sync --no-editable`) and standardized working directories.
- Updated `testcontainers` fixture imports in `tests/adapters/conftest.py` to support `testcontainers.community.*` package structures with fallback support.
- Restricted GitHub Actions CI workflow concurrency and cancellation strictly to pull requests.
- Upgraded `cryptography` dependency to `>=50.0.0`.

### Fixed

- Implemented explicit top-level transaction (`_top_xact`) rollback handling in `PostgresAdapter` on connection reset to prevent leaks of unhandled or aborted transaction states.
- Stabilized async pool connection release test timing in `tests/engine/test_pool.py`.
- Added warning filter configuration in `pyproject.toml` to suppress `testcontainers` deprecation warnings during test execution.

### Removed

- Removed unused legacy dependency injection container (`src/teridex_core/di.py`).

## [1.0.0] - 2026-08-06

### Chore

- Promoted package version to 1.0.0 for initial official PyPI release.

## [0.7.1] - 2026-08-01

### Added

- Added optional bulk schema introspection hooks (`fetch_all_columns`, `fetch_all_foreign_keys`, `fetch_all_indexes`) to `BaseIntrospector` allowing database adapters to batch-fetch schema metadata.
- Implemented bulk introspection methods in `PostgreSQLIntrospector` to fetch foreign keys and indexes across all schemas in single database queries, significantly speeding up schema discovery.

### Changed

- Optimized TUI `ResultsTable` row insertion by batch-adding datasets up to 1,000 rows directly without async yielding overhead.
- Pre-cached command title search strings and lookup mappings in `CommandPaletteScreen`, limiting fuzzy extraction results to 15 items for improved command palette responsiveness.
- Updated `README.md` project documentation.

## [0.7.0] - 2026-07-27

### Added

- Modularized database schema introspection into dedicated per-adapter modules (`teridex_adapters.introspect` for DuckDB, MySQL, PostgreSQL, and SQLite).
- Added Vim mode keybinding hints (`gg` / `G`) in the TUI status bar footer when Vim navigation mode is active.

### Changed

- Optimized TUI results table rendering performance by increasing row chunk size to 500 rows and displaying `NULL` values formatted with `[dim]NULL[/]`.
- Refactored `ConnectionPool` connection task creation to execute asynchronously outside the state lock and avoid potential lock contention.
- Updated project documentation including `README.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, `LICENSE`, and `SECURITY.md`.

### Fixed

- Ensured queries failing with a `QueryError` are correctly recorded in the TUI query history log.
- Cleaned up trailing whitespace in database adapter implementations and core connection models.

### Security

- Updated Docker base image to Python 3.15-rc-alpine to address base image OS package vulnerabilities.

## [0.6.0] - 2026-07-18

### Added

- Introduced `AdapterConnectionError` exception to handle and propagate connection failures uniformly across all database adapters.
- Implemented connection sharing for in-memory databases (SQLite and DuckDB), ensuring the schema introspector and query execution pool reuse the same database instance.

### Changed

- Removed the unused `Result` wrapper class (`Ok`/`Err` types) from the core codebase.
- Optimized the schema tree population in the TUI (`SchemaTree`) by utilizing `node.children` directly rather than tracking populated nodes in a separate set.
- Refactored connection selection in the `ConnectionScreen` modal to automatically submit the form when a DSN is selected.
- Updated container integration tests to dynamically parse and strip driver schemes (e.g., `+psycopg`, `+pymysql`) from connection URLs.
- Configured CI workflows to conditionally restrict integration tests to `ubuntu-latest` environments.

### Fixed

- Added escaping using `rich.markup.escape` to connection, validation, and query error strings in the TUI to prevent Rich markup injection or rendering issues.
- Optimized query execution result feeding by immediately halting table updates once the results table indicates truncation (e.g., limit is reached).
- Added automatic permission hardening (applying `0o600` permissions) to the Teridex configuration file if it is detected to have group/world-writable permissions.
- Ensured a `QueryCompleted` event is correctly emitted on `GeneratorExit` within the query executor, ensuring proper cleanup and statistics tracking when a query is cancelled.
- Fixed release checksum (`SHA256SUMS`) generation by running the checksum command directly inside the package distribution directory.

## [0.5.0] - 2026-07-12

### Added

- Context manager support (`__aenter__`/`__aexit__`) for database adapters to automatically handle connections.
- TUI Row Limit configuration screen (`RowLimitModal`) allowing dynamic customization of the display limit.
- New test suite for the row limit modal in `tests/tui/test_row_limit.py`.
- Project configuration file `mypy.ini` with strict check overrides for specific packages.

### Changed

- Refactored `TeridexConfig` configuration parsing model from Pydantic's `BaseSettings` to `BaseModel` and `ConfigDict`.
- Cached results table rows internally in `self._rows` to improve CSV export behavior and speed.
- `StatusBar` uses `Text.from_markup().plain` to calculate the visual footer width accurately.
- `Dsn` userinfo rendering handles standalone username or password fields correctly without assuming both exist.
- Invalid panel placements in custom plugins now fall back safely to `"bottom"`.

### Fixed

- Avoided closing standard error stream on log reconfiguration during tests to prevent ValueError warnings from cached loggers.
- Safely clean up and cancel active query tasks in `on_unmount()` when shutting down the Textual app.
- Connection close handling in `MySQLAdapter` uses asynchronous `ensure_closed()` calls.
- Ensured CLI connection tests properly close the connection when a test ping fails.

## [0.4.0] - 2026-07-04

### Added

- Support for introspecting foreign keys and indexes in the DuckDB adapter.
- Dynamic categorization of keybindings in the TUI Help Modal, separating global panel navigation from Vim navigation bindings depending on the active keymap mode.
- Implementation of a global `PluginLoader.unload_all()` helper to safely and cleanly unload all active plugins.
- Containerized integration tests using `testcontainers` for PostgreSQL and MySQL adapters, running automatically if a local Docker daemon is active.

### Changed

- Dsn connection model password field is now typed as `SecretStr` (using Pydantic's `SecretStr`) to prevent credentials from being accidentally serialized, printed, or logged in plaintext.
- Schema introspection for MySQL and SQLite adapters improved to correctly support and group multi-column (composite) foreign keys.

### Fixed

- Query execution failure handling now catches all base exceptions (rather than just adapter-specific `QueryError`s) and wraps them as structured query failures with a proper `teridex.query.unexpected` error code.


## [0.3.0] - 2026-06-22

### Added

- Support for passing custom database connection parameters/options from DSN query strings (e.g., config, timeout, cache) to DuckDB, MySQL, and SQLite adapters.
- TUI Help Modal notes clarifying the Vim keybindings applicability (applies to global panel navigation, query editor remains in standard insert mode).

### Changed

- PostgreSQL adapter now utilizes standard DSN string rendering and validates parameters strictly, raising a structured `QueryError` on invalid parameter keys or gaps.
- Dockerfile updated to copy the unified `src/` directory and `README.md` file rather than legacy monorepo package folders.
- TUI Action Bar default transaction mode renamed from "Auto" to "Auto-Commit".
- TUI Action Bar limit displays "Limit Unlimited" when limit is configured to 0.
- Cleaned up unused `Theme.as_variables()` helper in the base TUI theme.

### Fixed

- Retention trim operations in `QueryHistory` are now committed immediately during engine database open.
- Schema tree introspection failures do not mark nodes as populated, allowing users to collapse/expand to retry introspecting failed objects.

## [0.2.1] - 2026-06-20

### Changed

- Upgraded cryptography dependency to >=48.0.1.
- Upgraded pydantic-settings dependency to >=2.14.2.

## [0.2.0] - 2026-06-13

### Added

- Database introspection locks to prevent concurrent schema introspection conflicts.

### Changed

- Optimized TUI rendering using asynchronous chunked feeding to improve frame rates and typing responsiveness in the results table.
- Limited command palette results to the top 15 matches to improve filtering performance.
- Pre-compiled regular expressions in the status bar to reduce render-pass CPU overhead.
- Cached logger instances on first use to improve structured log performance.

### Fixed

- Fixed release workflow checksum and artifact packaging selectors.
- Fixed setup-uv setup caching in GitHub Actions CI and release workflows.

## [0.1.0] - 2026-06-10

### Added

- First implementation of Teridex.