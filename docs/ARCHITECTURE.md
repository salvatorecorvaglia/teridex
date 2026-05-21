# Teridex Architecture

## Layering

Teridex follows a strict clean-architecture dependency rule: outer layers
depend on inner layers, never the reverse.

```
apps/teridex-cli      apps/teridex-tui
       │                     │
       └──────► teridex-plugins ──────────┐
       └──────► teridex-engine            │
       └──────► teridex-adapters          │
                       │                  │
                       └──► teridex-core ◄┘
```

* **`teridex-core`** — pure domain. Pydantic models, typed errors, the DI
  container, the event bus, configuration, structured logging, protocols.
  No I/O, no third-party DB drivers.
* **`teridex-adapters`** — concrete DB drivers behind a unified
  `DatabaseAdapter` protocol. One file per database. Async streaming,
  cancellation, schema introspection.
* **`teridex-engine`** — orchestration: `QueryExecutor`, `ConnectionPool`,
  `Introspector`, `QueryHistory`. Emits lifecycle events on the bus.
* **`teridex-plugins`** — public plugin API (`hook`, `Command`, `Panel`),
  `PluginContext`, entry-point loader.
* **`apps/teridex-cli`** — Typer-based entry point.
* **`apps/teridex-tui`** — Textual app composing all of the above.

## Async model

Every adapter exposes an async interface. The TUI runs on Textual's event
loop; queries run as async tasks. Long-running streams check a
per-handle cancellation flag at each batch.

Sync drivers (DuckDB) are wrapped via `asyncio.to_thread`; native async
drivers (`asyncpg`, `aiosqlite`, `asyncmy`) are used directly.

## Event bus

`teridex_core.events.EventBus` is the spine of the internal architecture.
Components publish typed Pydantic event subclasses; subscribers receive
them on their own coroutine. A slow subscriber cannot back-pressure the
publisher — each subscriber has its own bounded queue.

Lifecycle events:
* `ConnectionOpened`, `ConnectionClosed`
* `QueryStarted`, `QueryProgress`, `QueryCompleted`, `QueryFailed`, `QueryCancelled`
* `SchemaRefreshed`
* `PluginLoaded`, `PluginUnloaded`

## Dependency injection

`teridex_core.di.Container` is a tiny protocol-keyed registry with
singleton/transient scoping. Apps wire it at startup and seal it; runtime
code resolves by `Type[T]`.

## Plugin system

Plugins are Python packages exposing a `teridex.plugins` entry point.
The factory returns an object with:

```python
manifest: PluginManifest
def on_load(ctx: PluginContext) -> None
def on_unload(ctx: PluginContext) -> None
```

Within `on_load` a plugin can:
* `ctx.subscribe(EventType, async handler)` for hooks
* `ctx.register_command(Command(...))` to surface a palette entry
* `ctx.register_panel(Panel(...))` to contribute a docked widget

## Non-functional

* `mypy --strict`, `ruff` lint + format gates.
* Structured logging via `structlog`.
* Connection pool is bounded and lazy.
* Result rendering is virtualized by Textual's `DataTable`.
