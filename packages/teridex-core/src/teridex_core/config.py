"""Layered configuration: defaults → TOML file → env (`TERIDEX_*`) → CLI."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from teridex_core.errors import ConfigError


class UIConfig(BaseModel):
    theme: str = "monokai"
    keymap: Literal["default", "vim"] = "default"
    show_status_bar: bool = True
    row_batch_size: int = Field(default=1000, ge=10, le=100_000)


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


class TeridexConfig(BaseSettings):
    """Top-level Teridex settings.

    Env vars: ``TERIDEX_<section>__<field>``, e.g. ``TERIDEX_UI__THEME=nord``.
    """

    model_config = SettingsConfigDict(
        env_prefix="TERIDEX_",
        env_nested_delimiter="__",
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


def load_config(path: Path | None = None, **overrides: Any) -> TeridexConfig:
    """Load configuration. File is optional; env/CLI overrides win."""
    data: dict[str, Any] = {}
    cfg_path = path or default_config_path()
    if cfg_path.exists():
        try:
            with cfg_path.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(
                f"failed to read config at {cfg_path}",
                context={"path": str(cfg_path), "error": str(exc)},
            ) from exc

    data.update(overrides)
    try:
        return TeridexConfig.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(
            "invalid configuration",
            context={"path": str(cfg_path), "error": str(exc)},
        ) from exc
