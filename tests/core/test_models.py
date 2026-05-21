from __future__ import annotations

import pytest

from teridex_core.errors import ConfigError
from teridex_core.models.connection import Dsn
from teridex_core.models.query import QueryHandle, QueryStatus


def test_dsn_parse_sqlite() -> None:
    d = Dsn.parse("sqlite:///:memory:")
    assert d.scheme == "sqlite"
    assert d.database == ":memory:"


def test_dsn_parse_postgres() -> None:
    d = Dsn.parse("postgres://user:pw@localhost:5432/mydb?sslmode=require")
    assert d.scheme == "postgres"
    assert d.username == "user"
    assert d.password == "pw"
    assert d.host == "localhost"
    assert d.port == 5432
    assert d.database == "mydb"
    assert d.params["sslmode"] == "require"


def test_dsn_unknown_scheme_raises() -> None:
    with pytest.raises(Exception):
        Dsn.parse("oracle://foo")


def test_dsn_missing_scheme_raises() -> None:
    with pytest.raises(ConfigError):
        Dsn.parse("just-a-path")


def test_dsn_render_masks_password() -> None:
    d = Dsn.parse("postgres://u:secret@h:5432/db")
    out = d.render(mask_password=True)
    assert "secret" not in out
    assert "***" in out


def test_query_handle_lifecycle() -> None:
    h = QueryHandle(connection_id="c", sql="select 1")
    assert h.status == QueryStatus.PENDING
    h.mark_running()
    assert h.started_at is not None
    h.mark_done(QueryStatus.SUCCEEDED)
    assert h.finished_at is not None
    assert h.duration_ms is not None
