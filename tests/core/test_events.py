from __future__ import annotations

import asyncio

import pytest

from teridex_core.events import EventBus, QueryCompleted, QueryStarted


@pytest.mark.asyncio
async def test_subscribe_receives_event() -> None:
    bus = EventBus()
    seen: list[QueryStarted] = []

    async def handler(ev: QueryStarted) -> None:
        seen.append(ev)

    bus.subscribe(QueryStarted, handler)
    bus.publish(QueryStarted(query_id="q", connection_id="c", sql_preview="select 1"))
    # Yield so the drainer can fire.
    for _ in range(20):
        await asyncio.sleep(0)
        if seen:
            break
    assert len(seen) == 1
    assert seen[0].query_id == "q"
    await bus.close()


@pytest.mark.asyncio
async def test_only_matching_type_delivered() -> None:
    bus = EventBus()
    other: list[object] = []

    async def handler(ev: QueryStarted) -> None:
        other.append(ev)

    bus.subscribe(QueryStarted, handler)
    # Publish a different event type — should not be delivered.
    bus.publish(QueryCompleted(query_id="x", rows=1, duration_ms=1.0))
    for _ in range(20):
        await asyncio.sleep(0)
    assert other == []
    await bus.close()
