# Authoring Teridex Plugins

A Teridex plugin is an ordinary Python package that exposes a callable on
the `teridex.plugins` entry-point group.

## Minimal plugin

```python
# my_plugin/__init__.py
from teridex_core.protocols.plugin import PluginManifest
from teridex_plugins.api import Command
from teridex_plugins.context import PluginContext


class MyPlugin:
    manifest = PluginManifest(
        id="acme.hello",
        name="Hello",
        version="0.1.0",
        description="Says hello from the palette.",
    )

    def on_load(self, ctx: PluginContext) -> None:
        async def say_hello(ctx: PluginContext) -> None:
            ctx.logger.info("hello from %s", ctx.plugin_id)

        ctx.register_command(
            Command(
                id="acme.hello.say",
                title="Hello, Teridex!",
                handler=say_hello,
            )
        )

    def on_unload(self, ctx: PluginContext) -> None:
        pass


def factory() -> MyPlugin:
    return MyPlugin()
```

```toml
# pyproject.toml
[project.entry-points."teridex.plugins"]
acme-hello = "my_plugin:factory"
```

After installing the package into the same environment as Teridex, run
`teridex plugins list` to confirm discovery.

## Hooking into engine events

```python
from teridex_core.events import QueryStarted

class Telemetry:
    manifest = PluginManifest(id="acme.telemetry", name="Telemetry")

    def on_load(self, ctx: PluginContext) -> None:
        async def on_started(ev: QueryStarted) -> None:
            ctx.logger.info("query started", query_id=ev.query_id)

        ctx.subscribe(QueryStarted, on_started)

    def on_unload(self, ctx: PluginContext) -> None: ...
```

## Contributing UI panels

Implement a Textual widget and return it from a `Panel.factory`:

```python
from textual.widgets import Static
from teridex_plugins.api import Panel


def make_panel(ctx: PluginContext):
    return Static("Hello from the plugin panel!")


# inside on_load:
ctx.register_panel(
    Panel(id="acme.panel", title="Acme", placement="right", factory=make_panel)
)
```

## API stability

We versioned the plugin API independently of the rest of Teridex; only
symbols importable from `teridex_plugins` and `teridex_core.protocols`
are considered public.
