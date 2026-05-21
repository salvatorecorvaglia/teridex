from __future__ import annotations

import pytest

from teridex_core.result import Err, Ok


def test_ok_basics() -> None:
    r = Ok(5)
    assert r.is_ok()
    assert not r.is_err()
    assert r.unwrap() == 5
    assert r.map(lambda x: x * 2).unwrap() == 10


def test_ok_unwrap_or_returns_value_not_default() -> None:
    assert Ok(5).unwrap_or(99) == 5


def test_ok_map_err_is_noop() -> None:
    r = Ok(5)
    assert r.map_err(lambda _e: "ignored") is r


def test_err_basics() -> None:
    r = Err("boom")
    assert r.is_err()
    assert not r.is_ok()
    assert r.unwrap_or(7) == 7
    assert r.map_err(str.upper).error == "BOOM"


def test_err_map_is_noop() -> None:
    r: Err[str] = Err("boom")
    assert r.map(lambda x: x) is r


def test_err_unwrap_raises_runtime_error_for_non_exception() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        Err("boom").unwrap()


def test_err_unwrap_raises_stored_exception() -> None:
    class _BoomError(Exception):
        pass

    with pytest.raises(_BoomError):
        Err(_BoomError("kaboom")).unwrap()
