from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from teridex_core.config import load_config


def test_load_config_with_file(tmp_path: Path) -> None:
    cfg = tmp_path / "teridex.toml"
    cfg.write_text(
        dedent(
            """
            [ui]
            theme = "nord"
            keymap = "vim"

            [engine]
            pool_size = 8
            """
        )
    )
    out = load_config(cfg)
    assert out.ui.theme == "nord"
    assert out.ui.keymap == "vim"
    assert out.engine.pool_size == 8


def test_load_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    out = load_config(tmp_path / "absent.toml")
    assert out.ui.theme == "monokai"
    assert out.engine.pool_size == 5
