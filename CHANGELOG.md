# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-12

### Changed

- **Crash:** pressing `Escape` in the connection dialog raised `ScreenStackError`. Textual delivers one key press to a screen twice — the focused widget bubbles it up and the screen is offered it directly — so `cancel()` ran a second time after the modal had already been popped, and the second `dismiss` popped an empty stack. Since that dialog is what the app opens when started without a DSN, it was reachable on the first keystroke of a fresh install. Modal dismissal is idempotent now, for every modal.
- **Status messages were pushed off-screen on any normal terminal.** The footer rendered its full shortcut list first and right-aligned the status after it, so below roughly 140 columns the status — every error message included — fell off the right edge and was simply not drawn. An 80-column terminal is ordinary. The status now claims the space it needs and shortcut hints are dropped from the right to fit.
- **Severity messages in the status bar were unreadable, and one was invisible.** The footer's background is `$warning` (a light gold), so severity carried by text colour measured 1.00:1 for warnings — `$warning` on `$warning` — and 2.2:1 for errors. "not connected", "nothing to run", "cancelled" and "display truncated" were all in that first category. Severity now renders as an inverted chip (dark text on a severity-coloured block), which clears 3:1 against its own background and reads as a badge.
- The status bar takes plain text rather than markup. `StatusBar.message` is data now and the widget builds its own `Content`, so a driver message containing brackets renders verbatim with no escaping at the call site — the whole class of markup errors is gone from that surface rather than patched.
- Severity colours across the TUI use theme variables instead of hardcoded `red`/`yellow`/`green`, so they track the active theme. Note that Textual's markup and rich's are not interchangeable: `Tree` labels go through rich, which rejects `$variable` tags, so the schema tree resolves theme variables to concrete colours instead. Tests pin both halves of that distinction.
- The run summary ("2 rows · display capped at 10000") moved from the results grid to `#results-panel`. `border_subtitle` only renders on a widget that has a border, and the grid has none except the one the `:focus` rule added — so the row count was visible only while the grid happened to be focused.
- The Run Query button is no longer clipped. A Textual `Button` is three rows tall by default and the one-row action bar cut it to a single visible row.
- Focus indication no longer reflows the layout. `:focus` rules *added* a border to widgets that had none, shifting their content by two rows and two columns on every focus change; those widgets' panels already signal focus by recolouring a border that is always there. One idiom throughout now.
- Removed the permanently-static "Tx: Auto-Commit" label from the action bar. Nothing in the UI or CLI reaches `teridex_engine.transaction`, so the label implied a feature that is not wired up. The engine keeps its transaction support for plugins.
- Dropped a dead `layer: overlay` declaration (no `layers:` is defined anywhere) and renamed the four PascalCase modal container ids to kebab-case, matching every other id in the stylesheet.
- **`teridex run` and `teridex connect` now read the configuration file.** Neither ever called `load_config`, so `[engine] default_timeout_seconds`, `[logging] level` and every `TERIDEX_<section>__<field>` environment override applied to the TUI only — while the README documented the layering unconditionally. Both commands also accept `--config`, matching `tui`. `run --timeout` now defaults to `engine.default_timeout_seconds` instead of a hardcoded 60s; an explicit `--timeout` still wins, and `--timeout 0` still disables the timeout.
- `ui.theme` is a `Literal["monokai", "nord"]` rather than a bare string. An unrecognized name used to fall back to monokai at render time, which looked like the setting being ignored; a typo is now a startup error. A test keeps the literal in step with the theme registry.
- Configuration sections validate on assignment. Settings are mutated at runtime (the row-limit modal writes `ui.max_display_rows`), and those writes previously bypassed the field constraints that the same value would have hit coming from a config file.
- `teridex run` reports rows *printed* separately from rows *read* when `--limit` truncates the output — it could previously print 2 rows under a caption reading "5 row(s)".
- The per-adapter parameter-binding contract is documented on `DatabaseAdapter.execute`. Each adapter binds with its driver's native paramstyle (Postgres wants `{"1": v}`, MySQL `{"name": v}` for `%(name)s`, DuckDB `$name`, SQLite DB-API), so `params` is not portable across adapters. Documented rather than unified, which would break every caller.
- **Breaking (keybindings):** four bindings sat on keys Textual's `TextArea` already claims, and the focused widget wins — so with the SQL editor focused, which is the normal state while working, those keys did the editor's thing and the app's action never fired. `Ctrl+C` in particular did nothing to cancel a query while the help modal explicitly promised it did.
  - `Cancel query` moved from `Ctrl+C` to `Ctrl+B` (`Ctrl+C` is copy in the editor, and Textual's own `Screen`/`App` bind it too).
  - `Close tab` moved from `Ctrl+W` to `Ctrl+O` (`Ctrl+W` is delete-word-left).
  - `Copy cell` (`Ctrl+Y`) and `Export CSV` (`Ctrl+E`) keep their keys but are now declared on the results grid instead of app-wide. They fire only when that grid has focus — which is the only time they mean anything — and the editor is not on its focus chain, so the collision is gone without spending a key.
  - `tests/tui/test_keymap_conflicts.py` now asserts this property against the installed Textual, so a future release that claims another key fails CI rather than silently disabling a binding.
- The help modal renders keys the way the footer does (`^↵`, not `ctrl+enter`), collapses aliased bindings onto one row instead of listing "Run query" twice, and separates global from results-pane bindings. The stale note claiming `^c` cancels the query is gone.

### Security



- DSN query parameters carrying credentials (`?password=`, `?auth_token=`, anything whose name contains `password`/`passwd`/`pwd`/`secret`/`token`/`credential`) are now redacted by `mask_dsn_password` and by `Dsn.render(mask_password=True)`. Only the userinfo segment (`scheme://user:pw@host`) was masked before, so a secret passed as a query parameter was written verbatim to `~/.teridex/teridex.log`, shown in the status bar, and persisted as the `connection_label` of every query in `~/.teridex/history.db`. File-path parameters (`sslkey`, `sslcert`, `sslrootcert`) are deliberately left legible — they are not secrets, and redacting them makes a TLS misconfiguration unreadable.

### Fixed

- **Logging could break every subsequent log call.** `configure_logging` captured `sys.stderr` by value and structlog caches bound loggers on first use, so once anything swapped the real stream — pytest's per-test capture, a reconfiguration, a TUI taking over the terminal — those cached loggers kept writing to a closed handle and raised `ValueError: I/O operation on closed file`. The stream is now resolved per write.
- **MySQL results were never streamed.** The adapter used asyncmy's default cursor, which is *buffered*: `execute()` reads the entire result set into Python, so the `fetchmany` loop was slicing a list that had already been fully materialized. `batch_size` and the UI's display cap bounded no memory, peak usage was the size of the result set, and cancelling mid-stream had nothing left to cancel. Query execution now uses `SSCursor`. Measured over 300,000 rows against MySQL 8: time-to-first-batch went from 390 ms to 2.4 ms (96% of the query elapsed before the first row surfaced; now 1%), with total throughput unchanged. Catalog queries keep the buffered cursor — they are small and drained immediately, and an unbuffered cursor would hold the connection until read out.
- **Resource leak:** `MySQLAdapter.ping()` left its cursor open when `SELECT 1` failed.
- **The cancel key could not interrupt a running query.** A binding's action is awaited by the App's own message pump, and `action_run_query` drained the entire result stream inline — so the pump was occupied for the whole query and no further key was dispatched until it finished. The cancel key was inert during exactly the long query it exists to abort. Queries started from the Run *button* were unaffected (a `Button.Pressed` handler runs on the button's own pump), so the two entry points behaved differently. Streaming now runs on a worker; validation and the re-entrancy guard stay synchronous in the action.
- **Layout:** plugin panel rails were mounted outside the grid they were styled for. `grid.mount(rail, before=self._status())` looks like it targets the grid, but `Widget._find_mount_point` resolves a widget spot to `spot.parent` and ignores the receiver — and the status bar is a *sibling* of `#main-grid`, not a child. Both rails therefore landed under `MainScreen`: the `.with-right`/`.with-bottom` rules added grid tracks nothing occupied, `#main-grid.with-right #bottom-rail` could never match, and the rails rendered as stacked blocks rather than side and bottom rails. The panel test asserted only that the widget existed somewhere, which is what let it ship; it now asserts parentage and child order.
- **Crash:** an error toast rendered driver text as Rich markup, so a message containing an unbalanced bracket raised `MarkupError` from inside the toast's render, and one containing a bracketed identifier (`syntax error near [col]`) silently dropped it from the message. Toasts are now plain text. This affected every error path, since `_report_error` is the single funnel for connection, query, export, schema-refresh and plugin failures.
- **Crash:** typing a DSN containing `[/]` into the connection dialog raised `MarkupError` — the parse error embeds the offending input and the modal renders it as markup.
- `Dsn.parse` now raises `ConfigError` for an unsupported scheme or an unparseable port, instead of letting pydantic's `ValidationError` escape. Callers render the message straight to the user, so the leak put a multi-line pydantic dump on screen. The "valid schemes" list no longer uses square brackets, which Rich would eat.
- **Data correctness:** absolute database paths no longer degrade to relative ones across a DSN round-trip. `sqlite:////abs/foo.db` parses to `/abs/foo.db` but re-rendered as `sqlite:///abs/foo.db`, which reparses as the relative `abs/foo.db` — a different database. The rendered form is what the status bar shows and what query history stores, so re-running a history entry could open the wrong file.
- A driver-raised `TimeoutError` (asyncpg/asyncmy read timeouts) with the query timeout disabled no longer produces `TypeError: unsupported format string passed to NoneType.__format__`, which masked the real failure. The driver's error now propagates unchanged.
- **Resource leak:** closing a `ConnectionPool` while a connection was still being established permanently consumed a pool permit. The background cleanup that returns the permit caught only `Exception`, but `close()` cancels the connection task and `CancelledError` is a `BaseException`.

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

### Testing

- The adapter conformance contract now covers `fetch_foreign_keys` and `fetch_indexes`, and asserts that a full `introspect()` agrees with the lazy per-object calls the schema tree uses. Only `fetch_columns` was under contract before, so the two code paths could drift — and DuckDB's per-object foreign-key and index implementations had never executed once. Coverage of the four introspectors went from 23–70% to 95–100%.
- Two assertions that could pass vacuously were tightened: the per-query leak check used `getattr(adapter, "_cancel_flags", {}) == {}`, which succeeds on any adapter *lacking* the attribute, so a rename would have silently retired the check; and a cancellation test used `pytest.raises((QueryCancelledError, Exception))`, which `Exception` subsumes, asserting only that something went wrong.
- Filled the coverage holes that let this audit's bugs through: the connection dialog (38% → 96%), the pool's cancellation paths, `Introspector.update_object`, `HelpModal._render_bindings`, `HistoryModal.submit`, `open_session`'s partial-failure rollback, the adapter registry's optional-driver branches, and every branch of `infer_column_type_from_value` — SQLite's only source of column typing.
- Replaced wall-clock sleeps and fixed-count poll loops with `asyncio.Event` waits in the pool and introspector tests, which is the idiom `test_events.py` already demonstrated. `tests/engine/test_pool.py` went from 5.1s to 0.02s. The sleeps that remain are in cancellation tests, where the delay genuinely means "let the query get underway" against a real engine.
- Removed dead test scaffolding: the `supports_transactions` conformance knob no subclass ever overrode (making its `pytest.skip` unreachable) and the declared-but-unused `slow` marker.
- Raised the offline coverage gate from 79% to 84%. Offline coverage is 85.2%; with integration enabled it is 89.8%.

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