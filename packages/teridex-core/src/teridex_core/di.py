"""Tiny service container with singleton/transient scoping.

Designed for composition at app start — not for runtime hot-swapping. Threading
guarantees: registrations are not thread-safe; resolution is, after the
container is sealed via :meth:`Container.seal`.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from threading import RLock
from typing import Any, TypeVar, cast

from teridex_core.errors import DependencyResolutionError

T = TypeVar("T")

_Factory = Callable[["Container"], Any]


class Lifetime(StrEnum):
    SINGLETON = "singleton"
    TRANSIENT = "transient"


class _Registration:
    __slots__ = ("factory", "instance", "lifetime")

    def __init__(self, factory: _Factory, lifetime: Lifetime) -> None:
        self.factory = factory
        self.lifetime = lifetime
        self.instance: Any = None


class Container:
    """Type-keyed service registry.

    Register concrete implementations or factories by abstract type::

        c = Container()
        c.register(EventBus, lambda c: EventBus(), lifetime=Lifetime.SINGLETON)
        c.register_instance(MyService, MyService(...))
        bus = c.resolve(EventBus)
    """

    def __init__(self) -> None:
        self._registry: dict[type[Any], _Registration] = {}
        self._lock = RLock()
        self._sealed = False

    def register(
        self,
        interface: type[T],
        factory: Callable[[Container], T],
        *,
        lifetime: Lifetime = Lifetime.SINGLETON,
    ) -> None:
        if self._sealed:
            raise DependencyResolutionError(
                "container is sealed; cannot register after seal()",
                context={"interface": interface.__name__},
            )
        self._registry[interface] = _Registration(factory, lifetime)

    def register_instance(self, interface: type[T], instance: T) -> None:
        if self._sealed:
            raise DependencyResolutionError(
                "container is sealed; cannot register after seal()",
                context={"interface": interface.__name__},
            )
        reg = _Registration(lambda _c: instance, Lifetime.SINGLETON)
        reg.instance = instance
        self._registry[interface] = reg

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, interface: type[T]) -> T:
        reg = self._registry.get(interface)
        if reg is None:
            raise DependencyResolutionError(
                f"no registration for {interface.__name__}",
                context={"interface": interface.__name__},
            )
        if reg.lifetime is Lifetime.SINGLETON:
            with self._lock:
                if reg.instance is None:
                    reg.instance = reg.factory(self)
                return cast("T", reg.instance)
        return cast("T", reg.factory(self))

    def try_resolve(self, interface: type[T]) -> T | None:
        try:
            return self.resolve(interface)
        except DependencyResolutionError:
            return None

    def __contains__(self, interface: type[Any]) -> bool:
        return interface in self._registry
