from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from teridex_core.config import load_config

if TYPE_CHECKING:
    from pathlib import Path


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


def test_load_config_deep_merges_overrides(tmp_path: Path) -> None:
    cfg = tmp_path / "teridex.toml"
    cfg.write_text(
        dedent(
            """
            [ui]
            theme = "nord"
            keymap = "vim"
            """
        )
    )
    out = load_config(cfg, ui={"theme": "monokai"})
    assert out.ui.theme == "monokai"
    assert out.ui.keymap == "vim"


@pytest.mark.parametrize("set_scalar_first", [True, False])
def test_env_config_scalar_and_nested_conflict_is_order_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, set_scalar_first: bool
) -> None:
    """A scalar (``TERIDEX_ENGINE``) and a nested field (``TERIDEX_ENGINE__POOL_SIZE``)
    targeting the same section must resolve the same way regardless of which
    ``setenv`` call happens first — the merge must not depend on
    ``os.environ`` iteration order.
    """
    scalar = ("TERIDEX_ENGINE", '{"max_history_entries": 42}')
    nested = ("TERIDEX_ENGINE__POOL_SIZE", "8")
    ordered = [scalar, nested] if set_scalar_first else [nested, scalar]
    for name, value in ordered:
        monkeypatch.setenv(name, value)

    out = load_config(tmp_path / "absent.toml")

    assert out.engine.pool_size == 8
