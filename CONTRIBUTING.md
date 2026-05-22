# Contributing to Teridex

## Setup

```bash
git clone https://github.com/<you>/teridex.git
cd teridex
./scripts/dev.sh    # runs: uv sync --all-extras --all-packages --dev + pre-commit install
```

`uv` is required (`brew install uv` or see <https://docs.astral.sh/uv/>).

## Day-to-day commands

| Task | Command |
|---|---|
| All gates (lint + types + tests) | `./scripts/check.sh` |
| Format + autofix | `./scripts/fmt.sh` |
| Lint + type-check | `./scripts/lint.sh` |
| Run unit tests | `./scripts/test.sh` |
| Bring up integration DBs | `docker compose -f docker/docker-compose.yml up -d` |
| Run integration tests | `TERIDEX_PG_DSN=postgres://teridex:teridex@localhost:5432/teridex TERIDEX_MYSQL_DSN=mysql://teridex:teridex@localhost:3306/teridex TERIDEX_TEST_MARKERS=integration ./scripts/test.sh` |

`scripts/check.sh` forwards extra arguments to pytest, so
`./scripts/check.sh -k schema_tree -v` runs the full lint + type stack
and then a filtered test subset.

## Coding standards

* **Strict mypy** across the codebase; new code must type-check.
* **Ruff** for format + lint. Use `./scripts/fmt.sh` before committing.
* **Async-first**: no blocking I/O in adapters or the TUI event loop.
* **No silent excepts**: every except logs or re-raises.
* **Small modules**: prefer composition over inheritance.

## Layering rule

`teridex_core` depends on nothing internal. Outer packages may depend on
inner ones, never the reverse. `mypy --strict` enforces import
boundaries.

## Adding a database adapter

1. Subclass `AbstractAdapter` in `packages/teridex-adapters/src/teridex_adapters/<name>_adapter.py`.
2. Set `name: ClassVar[str]` and `schemes: ClassVar[tuple[str, ...]]`.
3. Implement `_do_connect`, `_do_close`, `ping`, `execute`, `stream`, `begin`, `introspect`.
4. Register the class in `teridex_adapters/registry.py::_build_default`.
5. Add a parametrized adapter test under `tests/adapters/` using the
   shared scenarios in `tests/adapters/_conformance.py`.

## Releasing

Releases are manual today. To cut one:

1. Update `CHANGELOG.md` (graduate the `[Unreleased]` stanza to the
   new version).
2. Bump `version = "x.y.z"` in every `pyproject.toml`
   (workspace root + 6 members) and `__version__` in
   `packages/teridex-core/src/teridex_core/__init__.py`.
3. Run `uv sync --all-extras --all-packages --dev` to refresh
   `uv.lock`.
4. `./scripts/check.sh` must exit 0.
5. Commit and tag `vx.y.z`.

A `.github/workflows/release.yml` that automates wheel builds + GHCR
publish is on the roadmap (gap #7).
