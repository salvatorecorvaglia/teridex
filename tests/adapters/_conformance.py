"""Shared adapter conformance suite.

Every adapter must behave the same way through the ``DatabaseAdapter``
protocol, because the engine and the TUI are written against that protocol and
nothing else. Subclass :class:`AdapterConformance`, provide an ``adapter``
fixture and the handful of dialect strings, and the whole contract is checked.

Divergences this suite exists to catch — each one was a real bug:

* ``execute()`` must surface a bad statement, rather than deferring the error
  to ``stream()`` where a different code path reports it.
* ``Column.type`` must be populated, not left ``UNKNOWN`` on adapters whose
  driver does not hand types over for free.
* ``reset()`` must unwind connection state, so a pooled connection never
  arrives inside someone else's transaction.
* An abandoned stream must not strand a cursor or a transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from teridex_core.errors import QueryCancelledError, QueryError
from teridex_core.models.result import ColumnType

if TYPE_CHECKING:
    from teridex_core.models.result import ResultBatch
    from teridex_core.protocols.adapter import DatabaseAdapter

_TABLE = "teridex_conformance"


async def drain(adapter: DatabaseAdapter, sql: str) -> list[tuple[Any, ...]]:
    """Run *sql* to completion and return its rows."""
    handle = await adapter.execute(sql)
    rows: list[tuple[Any, ...]] = []
    async for batch in await adapter.stream(handle):
        rows.extend(batch.rows)
    return rows


async def collect(adapter: DatabaseAdapter, sql: str, **kwargs: Any) -> list[ResultBatch]:
    handle = await adapter.execute(sql)
    return [batch async for batch in await adapter.stream(handle, **kwargs)]


class AdapterConformance:
    """Contract every adapter must satisfy. Subclass and supply ``adapter``."""

    # --- dialect knobs a subclass may override -------------------------
    #: DDL for a two-column table named ``teridex_conformance``.
    create_table_sql: ClassVar[str] = f"CREATE TABLE {_TABLE} (id INTEGER, name VARCHAR(32))"
    #: A statement that cannot parse on any engine.
    invalid_sql: ClassVar[str] = "SELCT NOT VALID SQL ("
    #: Expected native type substring for the ``name`` column, if checked.
    supports_transactions: ClassVar[bool] = True

    # --- lifecycle ------------------------------------------------------

    @pytest.mark.asyncio
    async def test_ping(self, adapter: DatabaseAdapter) -> None:
        assert await adapter.ping() is True

    @pytest.mark.asyncio
    async def test_create_insert_select_roundtrip(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        await drain(adapter, f"INSERT INTO {_TABLE} VALUES (1, 'a')")
        await drain(adapter, f"INSERT INTO {_TABLE} VALUES (2, 'b')")
        rows = await drain(adapter, f"SELECT id, name FROM {_TABLE} ORDER BY id")
        assert rows == [(1, "a"), (2, "b")]

    # --- result shape ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_columns_are_named_and_typed(self, adapter: DatabaseAdapter) -> None:
        """``Column.type`` must be inferred on every adapter, not left UNKNOWN."""
        await drain(adapter, self.create_table_sql)
        await drain(adapter, f"INSERT INTO {_TABLE} VALUES (7, 'seven')")
        batches = await collect(adapter, f"SELECT id, name FROM {_TABLE}")
        columns = next(b.columns for b in batches if b.columns)

        assert [c.name for c in columns] == ["id", "name"]
        assert columns[0].type is ColumnType.INTEGER
        assert columns[1].type is ColumnType.STRING

    @pytest.mark.asyncio
    async def test_empty_result_set_still_reports_columns(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        batches = await collect(adapter, f"SELECT id, name FROM {_TABLE}")
        assert batches, "an empty result set must still yield a terminal batch"
        assert batches[-1].is_last
        assert sum(len(b.rows) for b in batches) == 0
        assert [c.name for c in batches[-1].columns] == ["id", "name"]

    @pytest.mark.asyncio
    async def test_nulls_round_trip_as_none(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        await drain(adapter, f"INSERT INTO {_TABLE} VALUES (1, NULL)")
        rows = await drain(adapter, f"SELECT id, name FROM {_TABLE}")
        assert rows == [(1, None)]

    @pytest.mark.asyncio
    async def test_batches_respect_batch_size(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        for i in range(5):
            await drain(adapter, f"INSERT INTO {_TABLE} VALUES ({i}, 'x')")

        handle = await adapter.execute(f"SELECT id FROM {_TABLE}")
        sizes = [len(b.rows) async for b in await adapter.stream(handle, batch_size=2)]
        assert sum(sizes) == 5
        assert max(sizes) <= 2

    @pytest.mark.asyncio
    async def test_metadata_survives_the_stream(self, adapter: DatabaseAdapter) -> None:
        """Metadata describes the finished result, so it must outlive it."""
        await drain(adapter, self.create_table_sql)
        handle = await adapter.execute(f"SELECT id, name FROM {_TABLE}")
        async for _ in await adapter.stream(handle):
            pass
        meta = await adapter.metadata(handle)
        assert meta.column_names == ["id", "name"]

    # --- error handling -------------------------------------------------

    @pytest.mark.asyncio
    async def test_invalid_sql_raises_from_execute(self, adapter: DatabaseAdapter) -> None:
        """The error must surface from ``execute()``, uniformly across adapters.

        Postgres used to defer all work to ``stream()``, so a syntax error
        arrived from a different call than on every other adapter and callers
        had to handle both.
        """
        with pytest.raises(QueryError):
            await adapter.execute(self.invalid_sql)

    @pytest.mark.asyncio
    async def test_cancel_before_streaming_raises(self, adapter: DatabaseAdapter) -> None:
        handle = await adapter.execute("SELECT 1")
        await adapter.cancel(handle)
        with pytest.raises(QueryCancelledError):
            async for _ in await adapter.stream(handle):
                pass

    # --- reuse ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_reset_leaves_the_connection_usable(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        await adapter.reset()
        assert await adapter.ping() is True
        assert await drain(adapter, f"SELECT id FROM {_TABLE}") == []

    @pytest.mark.asyncio
    async def test_reset_rolls_back_an_open_transaction(self, adapter: DatabaseAdapter) -> None:
        """A pooled connection must never be handed on mid-transaction."""
        if not self.supports_transactions:
            pytest.skip("adapter does not expose transactions")
        await drain(adapter, self.create_table_sql)
        tx = await adapter.begin()
        # Entered by hand rather than with ``async with``: the point of the
        # test is that ``reset()`` ends the transaction, so letting the context
        # manager also try to commit it would fail on the way out.
        await tx.__aenter__()
        await drain(adapter, f"INSERT INTO {_TABLE} VALUES (99, 'uncommitted')")
        await adapter.reset()

        assert await drain(adapter, f"SELECT id FROM {_TABLE} WHERE id = 99") == [], (
            "reset() left uncommitted work visible on the connection"
        )

    @pytest.mark.asyncio
    async def test_abandoned_stream_does_not_wedge_the_connection(
        self, adapter: DatabaseAdapter
    ) -> None:
        """Stop reading mid-result, reset, and the connection must still work."""
        await drain(adapter, self.create_table_sql)
        for i in range(10):
            await drain(adapter, f"INSERT INTO {_TABLE} VALUES ({i}, 'x')")

        handle = await adapter.execute(f"SELECT id FROM {_TABLE}")
        stream = await adapter.stream(handle, batch_size=1)
        async for _ in stream:
            break
        await stream.aclose()  # type: ignore[attr-defined]
        await adapter.reset()

        assert len(await drain(adapter, f"SELECT id FROM {_TABLE}")) == 10

    @pytest.mark.asyncio
    async def test_drained_statements_release_per_query_state(
        self, adapter: DatabaseAdapter
    ) -> None:
        """Per-query bookkeeping must not survive a fully drained statement.

        Every statement allocates a cursor and a cancel flag. A statement that
        returns no columns (DDL/DML) is the trap: SQLite and MySQL used to
        ``return`` from ``stream()`` *above* the ``finally`` that releases
        them, leaking one of each per INSERT — unbounded over the life of a
        pooled connection.
        """
        await drain(adapter, self.create_table_sql)
        for i in range(5):
            await drain(adapter, f"INSERT INTO {_TABLE} VALUES ({i}, 'x')")
        await drain(adapter, f"SELECT id FROM {_TABLE}")

        assert getattr(adapter, "_cancel_flags", {}) == {}, "cancel flags accumulated"
        assert getattr(adapter, "_cursors", {}) == {}, "driver cursors accumulated"
        assert getattr(adapter, "_statements", {}) == {}, "prepared statements accumulated"

    # --- introspection --------------------------------------------------

    @pytest.mark.asyncio
    async def test_introspection_finds_the_table(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        snapshot = await adapter.introspect()
        found = [
            obj for objects in snapshot.schemas.values() for obj in objects if obj.name == _TABLE
        ]
        assert found, f"introspection missed {_TABLE}; saw {sorted(snapshot.schemas)}"
        assert [c.name for c in found[0].columns] == ["id", "name"]

    @pytest.mark.asyncio
    async def test_lazy_introspection_skips_columns(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        snapshot = await adapter.introspect(lazy=True)
        found = [
            obj for objects in snapshot.schemas.values() for obj in objects if obj.name == _TABLE
        ]
        assert found
        assert found[0].columns == [], "lazy introspection must not fetch columns"

    @pytest.mark.asyncio
    async def test_fetch_columns_describes_the_table(self, adapter: DatabaseAdapter) -> None:
        await drain(adapter, self.create_table_sql)
        snapshot = await adapter.introspect(lazy=True)
        schema = next(
            name
            for name, objects in snapshot.schemas.items()
            if any(o.name == _TABLE for o in objects)
        )
        columns = await adapter.fetch_columns(schema, _TABLE)
        assert [c.name for c in columns] == ["id", "name"]
        assert columns[0].type is ColumnType.INTEGER
        assert columns[1].type is ColumnType.STRING
