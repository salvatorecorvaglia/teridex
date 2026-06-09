from __future__ import annotations

import pytest

from teridex_core.di import Container, Lifetime
from teridex_core.errors import DependencyResolutionError


class IFoo:
    def hello(self) -> str:
        raise NotImplementedError


class Foo(IFoo):
    def __init__(self) -> None:
        self.count = 0

    def hello(self) -> str:
        self.count += 1
        return "hi"


def test_singleton_returns_same_instance() -> None:
    c = Container()
    c.register(IFoo, lambda _c: Foo(), lifetime=Lifetime.SINGLETON)
    a = c.resolve(IFoo)
    b = c.resolve(IFoo)
    assert a is b


def test_transient_returns_new_instances() -> None:
    c = Container()
    c.register(IFoo, lambda _c: Foo(), lifetime=Lifetime.TRANSIENT)
    assert c.resolve(IFoo) is not c.resolve(IFoo)


def test_register_instance() -> None:
    c = Container()
    inst = Foo()
    c.register_instance(IFoo, inst)
    assert c.resolve(IFoo) is inst


def test_missing_registration() -> None:
    c = Container()
    with pytest.raises(DependencyResolutionError):
        c.resolve(IFoo)


def test_seal_prevents_further_registration() -> None:
    c = Container()
    c.seal()
    with pytest.raises(DependencyResolutionError):
        c.register(IFoo, lambda _c: Foo())


def test_try_resolve_returns_none_when_missing() -> None:
    c = Container()
    assert c.try_resolve(IFoo) is None


def test_contains() -> None:
    c = Container()
    c.register(IFoo, lambda _c: Foo())
    assert IFoo in c
