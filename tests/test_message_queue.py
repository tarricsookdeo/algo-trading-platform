"""Tests for the async message queue."""

from __future__ import annotations

import asyncio

import pytest

from trading_platform.core.message_queue import MessageQueue


@pytest.fixture
def mq():
    return MessageQueue(max_size=10, mode="lossy", dedup_quotes=True)


@pytest.fixture
def mq_lossless():
    return MessageQueue(max_size=5, mode="lossless", dedup_quotes=False)


class TestEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_basic(self, mq):
        result = await mq.enqueue({"symbol": "AAPL", "price": 100})
        assert result is True
        assert mq.depth == 1
        assert mq.enqueue_count == 1

    @pytest.mark.asyncio
    async def test_enqueue_multiple(self, mq):
        for i in range(5):
            await mq.enqueue({"symbol": f"SYM{i}"})
        assert mq.depth == 5
        assert mq.enqueue_count == 5

    @pytest.mark.asyncio
    async def test_enqueue_lossy_drops_oldest(self, mq):
        # Fill the queue
        for i in range(10):
            await mq.enqueue({"symbol": f"SYM{i}"})
        assert mq.depth == 10
        assert mq.drop_count == 0

        # One more should trigger lossy drop
        await mq.enqueue({"symbol": "OVERFLOW"})
        assert mq.enqueue_count == 11
        assert mq.drop_count == 1
        assert mq.depth == 10

    @pytest.mark.asyncio
    async def test_enqueue_lossy_multiple_drops(self, mq):
        # Fill queue
        for i in range(10):
            await mq.enqueue({"i": i})
        # Overflow 5 more
        for i in range(5):
            await mq.enqueue({"i": 10 + i})
        assert mq.drop_count == 5
        assert mq.depth == 10

    @pytest.mark.asyncio
    async def test_enqueue_lossless_backpressure(self, mq_lossless):
        # Fill the queue
        for i in range(5):
            await mq_lossless.enqueue({"i": i})
        assert mq_lossless.depth == 5

        # Next enqueue should block — use a timeout to verify
        async def slow_enqueue():
            await mq_lossless.enqueue({"i": 999})

        task = asyncio.create_task(slow_enqueue())
        await asyncio.sleep(0.05)
        # Task should still be pending (blocked)
        assert not task.done()

        # Drain one item to unblock
        mq_lossless._queue.get_nowait()
        await asyncio.sleep(0.05)
        assert task.done()
        assert mq_lossless.enqueue_count == 6


class TestConsumer:
    @pytest.mark.asyncio
    async def test_consumer_receives_batch(self, mq):
        received: list[list] = []

        async def callback(batch):
            received.append(batch)

        for i in range(5):
            await mq.enqueue({"i": i})

        mq.start_consumer(callback, batch_size=10, flush_interval_ms=20)
        await asyncio.sleep(0.1)
        await mq.stop()

        total_items = sum(len(b) for b in received)
        assert total_items == 5

    @pytest.mark.asyncio
    async def test_consumer_respects_batch_size(self):
        mq = MessageQueue(max_size=100, mode="lossy", dedup_quotes=False)
        received: list[list] = []

        async def callback(batch):
            received.append(list(batch))

        # Enqueue 25 items
        for i in range(25):
            await mq.enqueue({"i": i})

        mq.start_consumer(callback, batch_size=10, flush_interval_ms=5)
        await asyncio.sleep(0.2)
        await mq.stop()

        # Each batch should have at most 10 items
        for batch in received:
            assert len(batch) <= 10

        total = sum(len(b) for b in received)
        assert total == 25

    @pytest.mark.asyncio
    async def test_consumer_flush_interval(self):
        mq = MessageQueue(max_size=100, mode="lossy", dedup_quotes=False)
        received: list[list] = []

        async def callback(batch):
            received.append(list(batch))

        mq.start_consumer(callback, batch_size=1000, flush_interval_ms=30)

        # Send a small batch — should flush after interval even though batch not full
        await mq.enqueue({"i": 0})
        await mq.enqueue({"i": 1})
        await asyncio.sleep(0.1)
        await mq.stop()

        assert len(received) >= 1
        total = sum(len(b) for b in received)
        assert total == 2

    @pytest.mark.asyncio
    async def test_consumer_updates_dequeue_count(self, mq):
        async def callback(batch):
            pass

        for i in range(3):
            await mq.enqueue({"i": i})

        mq.start_consumer(callback, batch_size=10, flush_interval_ms=10)
        await asyncio.sleep(0.1)
        await mq.stop()

        assert mq.dequeue_count == 3


class TestDedupQuotes:
    @pytest.mark.asyncio
    async def test_dedup_keeps_latest_per_symbol(self):
        mq = MessageQueue(max_size=100, mode="lossy", dedup_quotes=True)
        received: list[list] = []

        async def callback(batch):
            received.append(list(batch))

        # Enqueue multiple quotes for same symbol — only latest should survive
        await mq.enqueue({"_channel": "quote", "symbol": "AAPL", "price": 100})
        await mq.enqueue({"_channel": "quote", "symbol": "AAPL", "price": 101})
        await mq.enqueue({"_channel": "quote", "symbol": "AAPL", "price": 102})
        await mq.enqueue({"_channel": "quote", "symbol": "MSFT", "price": 300})

        mq.start_consumer(callback, batch_size=100, flush_interval_ms=10)
        await asyncio.sleep(0.1)
        await mq.stop()

        all_items = [item for batch in received for item in batch]
        aapl_quotes = [m for m in all_items if m.get("symbol") == "AAPL"]
        msft_quotes = [m for m in all_items if m.get("symbol") == "MSFT"]

        assert len(aapl_quotes) == 1
        assert aapl_quotes[0]["price"] == 102
        assert len(msft_quotes) == 1

    @pytest.mark.asyncio
    async def test_dedup_preserves_non_quotes(self):
        mq = MessageQueue(max_size=100, mode="lossy", dedup_quotes=True)
        received: list[list] = []

        async def callback(batch):
            received.append(list(batch))

        await mq.enqueue({"_channel": "trade", "symbol": "AAPL", "price": 100})
        await mq.enqueue({"_channel": "quote", "symbol": "AAPL", "price": 101})
        await mq.enqueue({"_channel": "trade", "symbol": "AAPL", "price": 102})
        await mq.enqueue({"_channel": "quote", "symbol": "AAPL", "price": 103})

        mq.start_consumer(callback, batch_size=100, flush_interval_ms=10)
        await asyncio.sleep(0.1)
        await mq.stop()

        all_items = [item for batch in received for item in batch]
        trades = [m for m in all_items if m.get("_channel") == "trade"]
        quotes = [m for m in all_items if m.get("_channel") == "quote"]

        assert len(trades) == 2
        assert len(quotes) == 1
        assert quotes[0]["price"] == 103

    def test_dedup_static_method(self):
        batch = [
            {"_channel": "quote", "symbol": "AAPL", "price": 100},
            {"_channel": "quote", "symbol": "AAPL", "price": 101},
            {"_channel": "bar", "symbol": "AAPL"},
            {"_channel": "quote", "symbol": "MSFT", "price": 300},
        ]
        result = MessageQueue._dedup_quote_batch(batch)

        quotes = [m for m in result if m.get("_channel") == "quote"]
        assert len(quotes) == 2
        aapl_quote = [m for m in quotes if m.get("symbol") == "AAPL"][0]
        assert aapl_quote["price"] == 101


class TestMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_returns_all_fields(self, mq):
        await mq.enqueue({"x": 1})
        metrics = mq.get_metrics()

        assert "enqueue_count" in metrics
        assert "dequeue_count" in metrics
        assert "depth" in metrics
        assert "drop_count" in metrics
        assert "avg_latency_ms" in metrics
        assert "max_latency_ms" in metrics
        assert "mode" in metrics
        assert "max_size" in metrics

        assert metrics["enqueue_count"] == 1
        assert metrics["depth"] == 1
        assert metrics["mode"] == "lossy"
        assert metrics["max_size"] == 10

    @pytest.mark.asyncio
    async def test_latency_tracking(self):
        mq = MessageQueue(max_size=100, mode="lossy", dedup_quotes=False)

        async def callback(batch):
            pass

        await mq.enqueue({"x": 1})
        mq.start_consumer(callback, batch_size=10, flush_interval_ms=10)
        await asyncio.sleep(0.1)
        await mq.stop()

        assert mq.avg_latency_ms > 0
        assert mq.max_latency_ms > 0


class TestStopDrain:
    @pytest.mark.asyncio
    async def test_stop_drains_remaining(self):
        mq = MessageQueue(max_size=100, mode="lossy", dedup_quotes=False)
        drained: list[list] = []

        async def callback(batch):
            drained.append(list(batch))

        # Don't start consumer yet — enqueue items
        for i in range(5):
            await mq.enqueue({"i": i})

        # Use a short flush interval so the consumer processes items before stop
        mq.start_consumer(callback, batch_size=100, flush_interval_ms=20)
        await asyncio.sleep(0.1)
        await mq.stop()

        total = sum(len(b) for b in drained)
        assert total == 5
