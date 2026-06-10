"""Transaction helpers that surface adapter transactions through the engine."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from teridex_core.protocols.adapter import DatabaseAdapter, Transaction


@asynccontextmanager
async def transaction(adapter: DatabaseAdapter) -> AsyncIterator[Transaction]:
    """Open a transaction, commit on success, roll back on exception."""
    tx = await adapter.begin()
    try:
        async with tx as active:
            yield active
    except Exception:
        # ``__aexit__`` rolls back if it received an exception; re-raise.
        raise
