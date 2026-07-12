"""Layered configuration: defaults → TOML file → env (`TERIDEX_*`) → CLI."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from teridex_core.errors import ConfigError


class UIConfig(BaseModel):
    theme: str = "monokai"
    keymap: Literal["default", "vim"] = "default"
    show_status_bar: bool = True
    row_batch_size: int = Field(default=1000, ge=10, le=100_000)
    # Max rows held in the results grid. ``0`` means unlimited; a positive
    # cap protects memory on very large result sets.
    max_display_rows: int = Field(default=10_000, ge=0)


class EngineConfig(BaseModel):
    default_timeout_seconds: float = Field(default=60.0, gt=0)
    max_history_entries: int = Field(default=1000, ge=10)
    pool_size: int = Field(default=5, ge=1, le=64)


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # ``json_lines`` — emit one JSON object per line (CI/Docker). ``None``
    # auto-detects based on whether stderr is a TTY.
    json_lines: bool | None = None


class PluginsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)


class TeridexConfig(BaseModel):
    """Top-level Teridex settings.

    Env vars: ``TERIDEX_<section>__<field>``, e.g. ``TERIDEX_UI__THEME=nord``.
    """

    model_config = ConfigDict(
        extra="ignore",
        frozen=False,
    )

    ui: UIConfig = Field(default_factory=UIConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    connections: dict[str, str] = Field(default_factory=dict)


def default_config_path() -> Path:
    return Path.home() / ".config" / "teridex" / "config.toml"


def _deep_merge(base: dict[str, Any], custom: dict[str, Any]) -> dict[str, Any]:
    res = dict(base)
    for k, v in custom.items():
        if isinstance(v, dict) and k in res and isinstance(res[k], dict):
            res[k] = _deep_merge(res[k], v)
        else:
            res[k] = v
    return res


def _get_env_config() -> dict[str, Any]:
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415

    env_data: dict[str, Any] = {}
    for key, val in os.environ.items():
        if key.startswith("TERIDEX_"):
            name = key[len("TERIDEX_") :]
            if not name:
                continue
            parts = [p.lower() for p in name.split("__")]
            curr = env_data
            for part in parts[:-1]:
                if part in curr:
                    if not isinstance(curr[part], dict):
                        curr[part] = {}
                    curr = curr[part]
                else:
                    curr = curr.setdefault(part, {})
            # Try parsing values that look like JSON arrays/objects
            parsed_val: Any = val
            val_stripped = val.strip()
            if (val_stripped.startswith("[") and val_stripped.endswith("]")) or (
                val_stripped.startswith("{") and val_stripped.endswith("}")
            ):
                import contextlib  # noqa: PLC0415

                with contextlib.suppress(json.JSONDecodeError):
                    parsed_val = json.loads(val_stripped)
            curr[parts[-1]] = parsed_val
    return env_data


def load_config(path: Path | None = None, **overrides: Any) -> TeridexConfig:
    """Load configuration. File is optional; env/CLI overrides win."""
    toml_data: dict[str, Any] = {}
    cfg_path = path or default_config_path()
    if cfg_path.exists():
        try:
            with cfg_path.open("rb") as fh:
                toml_data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(
                f"failed to read config at {cfg_path}",
                context={"path": str(cfg_path), "error": str(exc)},
            ) from exc

    # Layer: TOML < Env Vars < CLI/Overrides
    data = _deep_merge(toml_data, _get_env_config())
    data = _deep_merge(data, overrides)
    try:
        return TeridexConfig.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(
            "invalid configuration",
            context={"path": str(cfg_path), "error": str(exc)},
        ) from exc
