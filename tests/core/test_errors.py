from __future__ import annotations

from teridex_core.errors import (
    AdapterConnectionError,
    AdapterError,
    ConfigError,
    PluginError,
    PluginLoadError,
    QueryCancelledError,
    QueryError,
    QueryTimeoutError,
    TeridexError,
)


def test_base_error_carries_message_and_context() -> None:
    err = TeridexError("boom", context={"key": "value"})
    assert err.message == "boom"
    assert err.context == {"key": "value"}
    assert str(err) == "[teridex.unknown] boom :: {'key': 'value'}"


def test_base_error_without_context_omits_the_context_suffix() -> None:
    err = TeridexError("boom")
    assert err.context == {}
    assert str(err) == "[teridex.unknown] boom"


def test_each_subclass_has_a_distinct_stable_code() -> None:
    assert ConfigError("x").code == "teridex.config"
    assert AdapterError("x").code == "teridex.adapter"
    assert AdapterConnectionError("x").code == "teridex.adapter.connection"
    assert QueryError("x").code == "teridex.query"
    assert QueryCancelledError("x").code == "teridex.query.cancelled"
    assert QueryTimeoutError("x").code == "teridex.query.timeout"
    assert PluginError("x").code == "teridex.plugin"
    assert PluginLoadError("x").code == "teridex.plugin.load"


def test_hierarchy_matches_the_documented_tree() -> None:
    assert issubclass(AdapterConnectionError, AdapterError)
    assert issubclass(QueryCancelledError, QueryError)
    assert issubclass(QueryTimeoutError, QueryError)
    assert issubclass(PluginLoadError, PluginError)
    for cls in (ConfigError, AdapterError, QueryError, PluginError):
        assert issubclass(cls, TeridexError)


def test_adapter_connection_error_does_not_shadow_the_builtin() -> None:
    # Deliberately not named ``ConnectionError`` — see the class docstring.
    assert not issubclass(AdapterConnectionError, ConnectionError)


def test_context_is_copied_not_aliased() -> None:
    ctx = {"a": 1}
    err = TeridexError("boom", context=ctx)
    ctx["a"] = 2
    assert err.context == {"a": 1}
