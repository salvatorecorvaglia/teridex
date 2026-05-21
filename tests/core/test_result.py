from __future__ import annotations

from teridex_core.result import Err, Ok


def test_ok_basics() -> None:
    r = Ok(5)
    assert r.is_ok()
    assert not r.is_err()
    assert r.unwrap() == 5
    assert r.map(lambda x: x * 2).unwrap() == 10


def test_err_basics() -> None:
    r = Err("boom")
    assert r.is_err()
    assert not r.is_ok()
    assert r.unwrap_or(7) == 7
    assert r.map_err(str.upper).error == "BOOM"
