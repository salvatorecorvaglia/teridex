# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Cleaned up obsolete PyPI publish attestation options in the release workflow.

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