"""A lightweight ``Result[T, E]`` type for fallible boundary operations.

We don't use this everywhere — internal happy paths still raise. ``Result`` is
for explicit, branching error handling at module boundaries (e.g. adapter
``connect`` returning either a connected handle or a typed error the UI can
render without a try/except).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")
U = TypeVar("U")
E = TypeVar("E")
F = TypeVar("F")


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self.value

    def unwrap_or(self, _default: T) -> T:
        return self.value

    def map(self, fn: Callable[[T], U]) -> Ok[U]:
        return Ok(fn(self.value))

    def map_err(self, _fn: Callable[[object], F]) -> Ok[T]:
        return self


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> NoReturn:
        raise self.error if isinstance(self.error, BaseException) else RuntimeError(self.error)

    def unwrap_or(self, default: T) -> T:
        return default

    def map(self, _fn: Callable[[object], U]) -> Err[E]:
        return self

    def map_err(self, fn: Callable[[E], F]) -> Err[F]:
        return Err(fn(self.error))


type Result[T, E] = Ok[T] | Err[E]
