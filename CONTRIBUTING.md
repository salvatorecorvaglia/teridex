# Contributing to Teridex 📟

Thank you for your interest in contributing to **Teridex**! This guide will help you set up your local development environment, walk you through our codebase structure, and outline our coding guidelines.

---

## 🛠️ Development Setup

Teridex uses [uv](https://github.com/astral-sh/uv) for fast, modern Python package management and workflow orchestration.

### Prerequisites

- **Python 3.13 or newer**
- **uv** (Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` or your package manager)

### Quick Start

1. **Fork and Clone the Repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/teridex.git
   cd teridex
   ```

2. **Synchronize Dependencies**
   Initialize the virtual environment and install all packages (including development packages and all database extras):
   ```bash
   uv sync --all-extras
   ```

3. **Activate the Environment**
   ```bash
   source .venv/bin/activate
   ```

---

## ⚙️ Coding Standards & Tools

We use strict quality gates to maintain codebase health. All of these run automatically on CI, but you should run them locally.

### Linting & Formatting

We use **Ruff** for formatting and linting, and **MyPy** for strict static type checking.

- **Check code formatting:**
  ```bash
  uv run ruff format --check .
  ```
- **Automatically format code:**
  ```bash
  uv run ruff format .
  ```
- **Lint code:**
  ```bash
  uv run ruff check .
  ```
- **Strict type check:**
  ```bash
  uv run mypy --config-file=mypy.ini src
  ```

Alternatively, you can run our developer linting script:
```bash
./scripts/lint.sh
```

---

## 🧪 Testing

We use **Pytest** for running our test suite.

- **Run all unit tests:**
  ```bash
  uv run pytest -m "not integration" --cov=src
  ```
- **Run integration tests (requires docker/live DBs):**
  ```bash
  uv run pytest -m "integration" --cov=src
  ```

Alternatively, you can use the test developer script:
```bash
./scripts/test.sh
```

### The Ultimate Quality Gate

Before submitting any Pull Request, make sure the entire suite (formatting, linting, type-checking, and tests) passes by running:
```bash
./scripts/check.sh
```

---

## 🔌 Writing Plugins

Teridex is pluggable. You can contribute new plugins by subclassing the plugin interface and implementing the hooks or panels.

### Event Bus Hooks
Plugins can subscribe to events published on the async `EventBus`. Key events defined in [events.py](src/teridex_core/events.py) include:

- `ConnectionOpened` / `ConnectionClosed`
- `QueryStarted` / `QueryProgress` / `QueryCompleted` / `QueryFailed` / `QueryCancelled`
- `SchemaRefreshed`
- `PluginLoaded` / `PluginUnloaded`

Example usage in a plugin:
```python
from teridex_plugins.api import hook


@hook("query.before_execute")
async def log_query(self, ctx, sql: str) -> None:
    # Do something async before query runs
    ...
```

---

## 📥 Submitting a Pull Request

1. Create a logical feature branch: `git checkout -b feature/my-cool-feature`.
2. Write tests covering your implementation.
3. Verify that `./scripts/check.sh` passes successfully.
4. Commit your changes with clear, descriptive commit messages.
5. Push to your fork and open a Pull Request.

---

Happy coding! 📟