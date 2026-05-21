# Contributing to Teridex

## Setup

```bash
git clone https://github.com/<you>/teridex.git
cd teridex
./scripts/dev.sh
```

`uv` is required (`brew install uv` or see <https://docs.astral.sh/uv/>).

## Day-to-day commands

| Task | Command |
|---|---|
| Format + autofix | `./scripts/fmt.sh` |
| Lint + type-check | `./scripts/lint.sh` |
| Run unit tests | `./scripts/test.sh` |
| Bring up integration DBs | `docker compose -f docker/docker-compose.yml up -d` |
| Run integration tests | `TERIDEX_TEST_MARKERS="integration" ./scripts/test.sh` |

## Coding standards

* **Strict mypy** across the codebase; new code must type-check.
* **Ruff** for format + lint. Use `./scripts/fmt.sh` before committing.
* **Async-first**: no blocking I/O in adapters or the TUI event loop.
* **No silent excepts**: every except logs or re-raises.
* **Small modules**: prefer composition over inheritance.

## Layering rule

`teridex_core` depends on nothing internal. Outer packages may depend on
inner ones, never the reverse. CI's mypy strict config enforces import
boundaries.

## Adding a database adapter

1. Subclass `AbstractAdapter` in `packages/teridex-adapters/src/teridex_adapters/<name>_adapter.py`.
2. Set `name: ClassVar[str]` and `schemes: ClassVar[tuple[str, ...]]`.
3. Implement `_do_connect`, `_do_close`, `ping`, `execute`, `stream`, `begin`, `introspect`.
4. Register the class in `registry._build_default`.
5. Add a parametrized adapter test under `tests/adapters/`.

