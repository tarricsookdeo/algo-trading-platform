"""Integration test: full flow ingestion → queue → consumer → EventBus.

Also includes a benchmark test pushing 10K messages through the queue.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from trading_platform.core.events import EventBus
from trading_platform.core.message_queue import MessageQueue
from trading_platform.core.metrics import PerformanceMetrics
from trading_platform.data.config import DataConfig
from trading_platform.data.manager import DataManager


class TestFullFlowIntegration:
    """Test the complete ingestion → MQ → consumer → EventBus path."""

    @pytest.mark.asyncio
    async def test_ingestion_through_queue_to_eventbus(self):
        bus = EventBus()
        perf = PerformanceMetrics()
        mq = MessageQueue(max_size=1000, mode="lossy", dedup_quotes=True)

        received_events: list[dict] = []

        async def on_bar(channel, event):
            received_events.append(event)

        await bus.subscribe("bar", on_bar)

        # Consumer callback mirrors main.py
        async def consumer_callback(batch):
            for msg in batch:
                channel = msg.pop("_channel", None)
                if channel:
                    await bus.publish(channel, msg)
                    perf.record_processed()

        mq.start_consumer(consumer_callback, batch_size=50, flush_interval_ms=10)

        # Create DataManager wired through MQ
        cfg = DataConfig()
        dm = DataManager(bus, config=cfg, message_queue=mq, perf_metrics=perf)

        # Publish bars through DataManager
        for i in range(20):
            await dm.publish_bar({
                "symbol": f"SYM{i}",
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 1000,
            })

        # Wait for consumer to process
        await asyncio.sleep(0.2)
        await mq.stop()

        assert len(received_events) == 20
        assert perf.messages_received == 20
        assert perf.messages_processed == 20
        assert dm.bars_received == 20

    @pytest.mark.asyncio
    async def test_quote_dedup_in_flow(self):
        bus = EventBus()
        mq = MessageQueue(max_size=1000, mode="lossy", dedup_quotes=True)

        received_quotes: list[dict] = []

        async def on_quote(channel, event):
            received_quotes.append(event)

        await bus.subscribe("quote", on_quote)

        async def consumer_callback(batch):
            for msg in batch:
                channel = msg.pop("_channel", None)
                if channel:
                    await bus.publish(channel, msg)

        mq.start_consumer(consumer_callback, batch_size=1000, flush_interval_ms=5)

        dm = DataManager(bus, message_queue=mq)

        # Send many quotes for same symbol rapidly
        for i in range(50):
            await dm.publish_quote({"symbol": "AAPL", "price": 100.0 + i})

        await asyncio.sleep(0.2)
        await mq.stop()

        # With dedup, we should have fewer than 50 AAPL quotes
        aapl_quotes = [q for q in received_quotes if q.get("symbol") == "AAPL"]
        assert len(aapl_quotes) < 50
        # But we should have at least 1
        assert len(aapl_quotes) >= 1
        # Latest price should be present
        assert any(q["price"] == 149.0 for q in aapl_quotes)

    @pytest.mark.asyncio
    async def test_mixed_channels_through_queue(self):
        bus = EventBus()
        mq = MessageQueue(max_size=1000, mode="lossy", dedup_quotes=False)

        bars = []
        quotes = []
        trades = []

        async def on_bar(ch, ev):
            bars.append(ev)

        async def on_quote(ch, ev):
            quotes.append(ev)

        async def on_trade(ch, ev):
            trades.append(ev)

        await bus.subscribe("bar", on_bar)
        await bus.subscribe("quote", on_quote)
        await bus.subscribe("trade", on_trade)

        async def consumer_callback(batch):
            for msg in batch:
                channel = msg.pop("_channel", None)
                if channel:
                    await bus.publish(channel, msg)

        mq.start_consumer(consumer_callback, batch_size=50, flush_interval_ms=10)
        dm = DataManager(bus, message_queue=mq)

        await dm.publish_bar({"symbol": "AAPL", "open": 100})
        await dm.publish_quote({"symbol": "AAPL", "price": 100})
        await dm.publish_trade({"symbol": "AAPL", "price": 100, "size": 10})

        await asyncio.sleep(0.2)
        await mq.stop()

        assert len(bars) == 1
        assert len(quotes) == 1
        assert len(trades) == 1

    @pytest.mark.asyncio
    async def test_lossy_mode_drops_under_pressure(self):
        mq = MessageQueue(max_size=10, mode="lossy", dedup_quotes=False)

        received: list[list] = []

        async def callback(batch):
            received.append(list(batch))

        # Enqueue 20 items into a size-10 queue
        for i in range(20):
            await mq.enqueue({"_channel": "bar", "i": i})

        assert mq.drop_count == 10
        assert mq.depth == 10

        mq.start_consumer(callback, batch_size=100, flush_interval_ms=10)
        await asyncio.sleep(0.1)
        await mq.stop()

        total = sum(len(b) for b in received)
        assert total == 10


class TestBenchmark:
    """Benchmark: push 10K messages through the queue and verify throughput."""

    @pytest.mark.asyncio
    async def test_10k_messages_throughput(self):
        mq = MessageQueue(max_size=50_000, mode="lossy", dedup_quotes=False)
        processed_count = 0

        async def callback(batch):
            nonlocal processed_count
            processed_count += len(batch)

        mq.start_consumer(callback, batch_size=200, flush_interval_ms=5)

        n = 10_000
        start = time.monotonic()
        for i in range(n):
            await mq.enqueue({"_channel": "bar", "i": i})
        enqueue_elapsed = time.monotonic() - start

        # Wait for consumer to finish
        for _ in range(50):
            await asyncio.sleep(0.05)
            if processed_count >= n:
                break

        await mq.stop()
        total_elapsed = time.monotonic() - start

        assert processed_count == n
        assert mq.drop_count == 0

        # Throughput should be reasonable (at least 5K/sec on any machine)
        enqueue_rate = n / max(enqueue_elapsed, 0.001)
        assert enqueue_rate > 5000, f"enqueue rate too low: {enqueue_rate:.0f}/sec"

    @pytest.mark.asyncio
    async def test_10k_with_dedup(self):
        mq = MessageQueue(max_size=50_000, mode="lossy", dedup_quotes=True)
        processed_count = 0

        async def callback(batch):
            nonlocal processed_count
            processed_count += len(batch)

        mq.start_consumer(callback, batch_size=200, flush_interval_ms=5)

        n = 10_000
        # All quotes for same symbol — heavy dedup
        for i in range(n):
            await mq.enqueue({"_channel": "quote", "symbol": "AAPL", "price": float(i)})

        for _ in range(50):
            await asyncio.sleep(0.05)
            if mq.depth == 0:
                break

        await mq.stop()

        # With dedup, processed count will be much less than n
        assert processed_count < n
        assert processed_count >= 1
        assert mq.drop_count == 0
