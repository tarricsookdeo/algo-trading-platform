"""Tests for the async event bus."""

import asyncio

import pytest

from trading_platform.core.events import EventBus


@pytest.fixture
def bus():
    return EventBus()


@pytest.mark.asyncio
async def test_publish_subscribe(bus):
    received = []

    async def handler(channel, event):
        received.append((channel, event))

    await bus.subscribe("trade", handler)
    await bus.publish("trade", {"symbol": "AAPL", "price": 150.0})

    assert len(received) == 1
    assert received[0][0] == "trade"
    assert received[0][1]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_wildcard_subscription(bus):
    received = []

    async def handler(channel, event):
        received.append(channel)

    await bus.subscribe("*", handler)
    await bus.publish("trade", "t1")
    await bus.publish("quote", "q1")
    await bus.publish("bar", "b1")

    assert received == ["trade", "quote", "bar"]


@pytest.mark.asyncio
async def test_unsubscribe(bus):
    received = []

    async def handler(channel, event):
        received.append(event)

    await bus.subscribe("trade", handler)
    await bus.publish("trade", "first")
    await bus.unsubscribe("trade", handler)
    await bus.publish("trade", "second")

    assert received == ["first"]


@pytest.mark.asyncio
async def test_multiple_subscribers(bus):
    results_a = []
    results_b = []

    async def handler_a(ch, ev):
        results_a.append(ev)

    async def handler_b(ch, ev):
        results_b.append(ev)

    await bus.subscribe("quote", handler_a)
    await bus.subscribe("quote", handler_b)
    await bus.publish("quote", "q1")

    assert results_a == ["q1"]
    assert results_b == ["q1"]


@pytest.mark.asyncio
async def test_metrics(bus):
    async def noop(ch, ev):
        pass

    await bus.subscribe("trade", noop)
    for _ in range(10):
        await bus.publish("trade", "x")

    assert bus.total_published == 10
    assert bus.channel_counts["trade"] == 10
    assert bus.events_per_second() > 0


@pytest.mark.asyncio
async def test_no_duplicate_subscribe(bus):
    async def handler(ch, ev):
        pass

    await bus.subscribe("trade", handler)
    await bus.subscribe("trade", handler)
    assert bus.subscriber_count == 1


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent(bus):
    """Unsubscribing a callback that was never subscribed should not raise."""
    async def handler(ch, ev):
        pass

    await bus.unsubscribe("trade", handler)  # should not raise
