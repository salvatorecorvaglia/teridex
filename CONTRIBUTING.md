# Contributing to Teridex 📟

## Setup

```bash
git clone https://github.com/<you>/teridex.git
cd teridex
./scripts/dev.sh    # runs: uv sync --all-extras --all-packages --dev
```

`uv` is required (`brew install uv` or see <https://docs.astral.sh/uv/>).

## Day-to-day commands

| Task                             | Command                                                                                                                                                                                |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| All gates (lint + types + tests) | `./scripts/check.sh`                                                                                                                                                                   |
| Format + autofix                 | `./scripts/fmt.sh`                                                                                                                                                                     |
| Lint + type-check                | `./scripts/lint.sh`                                                                                                                                                                    |
| Run unit tests                   | `./scripts/test.sh`                                                                                                                                                                    |
| Bring up integration DBs         | `docker compose -f docker/docker-compose.yml up -d`                                                                                                                                    |
| Run integration tests            | `TERIDEX_PG_DSN=postgres://teridex:teridex@localhost:5432/teridex TERIDEX_MYSQL_DSN=mysql://teridex:teridex@localhost:3306/teridex TERIDEX_TEST_MARKERS=integration ./scripts/test.sh` |

`scripts/check.sh` forwards extra arguments to pytest, so
`./scripts/check.sh -k schema_tree -v` runs the full lint + type stack
and then a filtered test subset.

## Pull request workflow

1. Fork the repository and create a feature branch from `main`.
2. Make your changes (see **Coding standards** below).
3. Run `./scripts/check.sh` and ensure it exits 0.
4. Commit with a clear, descriptive message.
5. Open a pull request against `main`.

CI (`.github/workflows/ci.yml`) will automatically lint, type-check, and run the test suite with a **70 % branch-coverage gate** on every PR. All checks must pass before merge.

## Test suites & structure

The test suite is partitioned to mirror the layered package structure. Run specific subsets by targeting their test files or using `-k` flags:

- **TUI & UI Component Tests** (`tests/tui/`): Covers screen and widget behavior, rendering states, help modals, schema tree displays, and vim keymap behavior (e.g., `test_app_smoke.py`, `test_schema_tree.py`, `test_results_pane.py`).
- **Adapter Conformance Tests** (`tests/adapters/`): Verifies database driver implementations. All adapters (DuckDB, SQLite, PostgreSQL, MySQL) must pass the shared conformance scenarios located in `tests/adapters/_conformance.py`.
- **Engine execution & Pool orchestration** (`tests/engine/`): Tests transaction boundaries, QueryExecutor, ConnectionPool behavior, and QueryHistory persistence.
- **Core logic & Infrastructure** (`tests/core/`): Tests dependency injection (`test_di.py`), JSON/structured logging formatters, custom configuration layers (`test_config.py`), and the event bus (`test_events.py`).
- **Plugin lifecycle** (`tests/plugins/`): Verifies API hooks, plugin load discovery, and context isolation.

### Coverage

The project enforces a **minimum 70 % branch coverage** gate (`fail_under = 70` in `pyproject.toml`). New code should include tests that maintain or improve coverage. Run `./scripts/test.sh` locally — it generates a `term-missing` coverage report so you can spot uncovered lines.

## Coding standards

- **Strict mypy** across the codebase; new code must type-check.
- **Ruff** for format + lint (line length: 100). Use `./scripts/fmt.sh` before committing.
- **Async-first**: no blocking I/O in adapters or the TUI event loop.
- **No silent excepts**: every except logs or re-raises.
- **Plugin Event Subscriptions**: Always register handlers via `PluginContext.subscribe` (which
  tracks them locally) instead of calling the event bus directly. This ensures dynamic plugin
  unloading does not leak subscriptions.
- **Adapter Locking Guidelines**: When implementing or editing adapters with blocking interfaces
  (such as DuckDB), ensure all operations that touch the connection handles are synchronized
  under the adapter's `self._lock` and offloaded using `asyncio.to_thread`.
- **Database Statement Classification**: Always inspect prepared statement attributes (such as
  `stmt.get_attributes()` in `asyncpg`) to differentiate query execution types (DQL/DML)
  instead of parsing raw string prefixes. This ensures robust handling of query comment headers
  and returning statements.
- **Small modules**: prefer composition over inheritance.
- **EditorConfig**: The project ships an `.editorconfig` (UTF-8, LF, 4-space indent, 2-space for YAML/TOML/JSON). Please ensure your editor respects it.

## Layering rule

`teridex_core` depends on nothing internal. Outer packages may depend on
inner ones, never the reverse. `mypy --strict` enforces import
boundaries.

```
teridex-core          ← pure domain (zero internal deps)
  └─ teridex-adapters ← DB drivers
  └─ teridex-plugins  ← plugin API
     └─ teridex-engine   ← orchestration
        └─ teridex-tui   ← Textual app
        └─ teridex-cli   ← Typer CLI
```

## Adding a database adapter

1. Subclass `AbstractAdapter` in `packages/teridex-adapters/src/teridex_adapters/<name>_adapter.py`.
2. Set `name: ClassVar[str]` and `schemes: ClassVar[tuple[str, ...]]`.
3. Implement `_do_connect`, `_do_close`, `ping`, `execute`, `stream`, `begin`, `introspect`.
4. Register the class in `teridex_adapters/registry.py::_build_default`.
5. Add a parametrized adapter test under `tests/adapters/` using the
   shared scenarios in `tests/adapters/_conformance.py`.

## Releasing

Releases are automated via GitHub Actions (`.github/workflows/release.yml`) when a version tag is pushed. To prepare and cut a release:

1. Update `CHANGELOG.md` (graduate the `[Unreleased]` stanza to the new version).
2. Bump `version = "x.y.z"` in every `pyproject.toml` (workspace root + 6 member packages) and `__version__` in `packages/teridex-core/src/teridex_core/__init__.py`.
3. Run `uv sync --all-extras --all-packages --dev` to refresh `uv.lock`.
4. Run `./scripts/check.sh` and ensure it exits 0.
5. Commit your changes to `main` and push them.
6. Create and push a version tag (e.g. `vx.y.z`):
    ```bash
    git tag vx.y.z
    git push origin vx.y.z
    ```

The release workflow will automatically trigger on tag push to:

- Run all quality gates (linting + mypy + pytest).
- Generate a new GitHub release with release notes.

## 📜 Code of Conduct

Please maintain a respectful and professional tone in all communications.

---

Happy coding! 📟
