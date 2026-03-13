"""Tests for the DashboardThrottler."""

from __future__ import annotations

import asyncio

import pytest

from trading_platform.dashboard.throttler import DashboardThrottler


@pytest.fixture
def throttler():
    return DashboardThrottler(flush_interval_ms=50, max_trades_per_flush=5)


class TestBuffering:
    @pytest.mark.asyncio
    async def test_buffer_quote(self, throttler):
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 185.0})
        assert throttler.events_buffered == 1
        assert "AAPL" in throttler._quotes

    @pytest.mark.asyncio
    async def test_buffer_trade(self, throttler):
        await throttler.buffer_event("trade", {"symbol": "AAPL", "price": 185.0})
        assert throttler.events_buffered == 1
        assert len(throttler._trades) == 1

    @pytest.mark.asyncio
    async def test_buffer_bar(self, throttler):
        await throttler.buffer_event("bar", {"symbol": "AAPL", "open": 185.0})
        assert throttler.events_buffered == 1
        assert "AAPL" in throttler._bars

    @pytest.mark.asyncio
    async def test_buffer_other_channel(self, throttler):
        await throttler.buffer_event("system", {"msg": "hello"})
        assert throttler.events_buffered == 1
        assert len(throttler._other) == 1


class TestDedup:
    @pytest.mark.asyncio
    async def test_quote_dedup_by_symbol(self, throttler):
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 100})
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 101})
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 102})

        # Only latest should be in buffer
        assert len(throttler._quotes) == 1
        assert throttler._quotes["AAPL"]["data"]["price"] == 102

    @pytest.mark.asyncio
    async def test_bar_dedup_by_symbol(self, throttler):
        await throttler.buffer_event("bar", {"symbol": "AAPL", "open": 100})
        await throttler.buffer_event("bar", {"symbol": "AAPL", "open": 101})

        assert len(throttler._bars) == 1
        assert throttler._bars["AAPL"]["data"]["open"] == 101

    @pytest.mark.asyncio
    async def test_multiple_symbols_kept(self, throttler):
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 100})
        await throttler.buffer_event("quote", {"symbol": "MSFT", "price": 300})

        assert len(throttler._quotes) == 2

    @pytest.mark.asyncio
    async def test_quote_without_symbol_goes_to_other(self, throttler):
        await throttler.buffer_event("quote", {"price": 100})
        assert len(throttler._quotes) == 0
        assert len(throttler._other) == 1


class TestFlush:
    @pytest.mark.asyncio
    async def test_flush_sends_batch(self, throttler):
        flushed: list[dict] = []

        async def mock_broadcast(msg):
            flushed.append(msg)

        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 100})
        await throttler.buffer_event("trade", {"symbol": "AAPL", "price": 100})

        throttler._broadcast_fn = mock_broadcast
        await throttler._flush()

        assert len(flushed) == 1
        msg = flushed[0]
        assert msg["type"] == "batch"
        assert msg["count"] == 2
        assert len(msg["updates"]) == 2

    @pytest.mark.asyncio
    async def test_flush_clears_buffers(self, throttler):
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 100})
        await throttler.buffer_event("trade", {"symbol": "AAPL", "price": 100})
        await throttler.buffer_event("bar", {"symbol": "AAPL", "open": 100})

        throttler._broadcast_fn = self._noop_broadcast
        await throttler._flush()

        assert len(throttler._quotes) == 0
        assert len(throttler._trades) == 0
        assert len(throttler._bars) == 0

    @pytest.mark.asyncio
    async def test_flush_caps_trades(self):
        throttler = DashboardThrottler(flush_interval_ms=50, max_trades_per_flush=3)
        flushed: list[dict] = []

        async def mock_broadcast(msg):
            flushed.append(msg)

        for i in range(10):
            await throttler.buffer_event("trade", {"symbol": "AAPL", "price": 100 + i})

        throttler._broadcast_fn = mock_broadcast
        await throttler._flush()

        trades = [u for u in flushed[0]["updates"] if u["type"] == "trade"]
        assert len(trades) == 3

    @pytest.mark.asyncio
    async def test_flush_no_broadcast_when_empty(self, throttler):
        flushed: list[dict] = []

        async def mock_broadcast(msg):
            flushed.append(msg)

        throttler._broadcast_fn = mock_broadcast
        await throttler._flush()

        assert len(flushed) == 0

    @pytest.mark.asyncio
    async def test_flush_updates_metrics(self, throttler):
        async def mock_broadcast(msg):
            pass

        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 100})
        throttler._broadcast_fn = mock_broadcast
        await throttler._flush()

        assert throttler.flush_count == 1
        assert throttler.events_flushed == 1

    @staticmethod
    async def _noop_broadcast(msg):
        pass


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, throttler):
        async def mock_broadcast(msg):
            pass

        throttler.start(mock_broadcast)
        assert throttler._task is not None
        assert throttler._running is True
        await throttler.stop()

    @pytest.mark.asyncio
    async def test_stop_does_final_flush(self):
        throttler = DashboardThrottler(flush_interval_ms=10000, max_trades_per_flush=50)
        flushed: list[dict] = []

        async def mock_broadcast(msg):
            flushed.append(msg)

        throttler.start(mock_broadcast)
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 100})
        # Stop immediately — the long interval means the loop hasn't flushed yet
        await throttler.stop()

        assert any(m.get("type") == "batch" for m in flushed)

    @pytest.mark.asyncio
    async def test_periodic_flush(self):
        throttler = DashboardThrottler(flush_interval_ms=30, max_trades_per_flush=50)
        flushed: list[dict] = []

        async def mock_broadcast(msg):
            flushed.append(msg)

        throttler.start(mock_broadcast)
        await throttler.buffer_event("quote", {"symbol": "AAPL", "price": 100})
        await asyncio.sleep(0.1)
        await throttler.stop()

        assert throttler.flush_count >= 1


class TestPydanticEvent:
    @pytest.mark.asyncio
    async def test_model_dump_event(self, throttler):
        """Events with model_dump should be serialized properly."""

        class FakeModel:
            def model_dump(self, mode="python"):
                return {"symbol": "AAPL", "price": 100.0}

        await throttler.buffer_event("quote", FakeModel())
        # Should end up in _other since model_dump events lack .get("symbol")
        # (dict check fails — model_dump path creates the payload differently)
        assert throttler.events_buffered == 1
