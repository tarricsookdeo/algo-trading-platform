"""Tests for Performance Phase 1b: Hot Path Optimizations.

Covers all four optimizations:
1. Topic-Based EventBus Routing
2. Binary Serialization (MessagePack)
3. Connection Pooling for Public.com API
4. Conditional Strategy Evaluation
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from trading_platform.core.events import EventBus
from trading_platform.core.message_queue import MessageQueue
from trading_platform.core.models import Bar, QuoteTick, TradeTick
from trading_platform.data.serialization import Format, deserialize, detect_format, has_msgpack, serialize
from trading_platform.strategy.base import Strategy
from trading_platform.strategy.manager import StrategyManager, StrategyState


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_quote(symbol: str = "AAPL", bid: float = 150.0, ask: float = 150.05) -> QuoteTick:
    return QuoteTick(
        symbol=symbol,
        bid_price=bid,
        bid_size=100,
        ask_price=ask,
        ask_size=200,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )


def _make_trade(symbol: str = "AAPL", price: float = 150.25) -> TradeTick:
    return TradeTick(
        symbol=symbol,
        price=price,
        size=10,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )


def _make_bar(symbol: str = "AAPL", close: float = 150.0) -> Bar:
    return Bar(
        symbol=symbol,
        open=149.0,
        high=151.0,
        low=148.0,
        close=close,
        volume=100000,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )


class DummyStrategy(Strategy):
    """Minimal concrete strategy for testing."""

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, event_bus, config)
        self.quotes_seen: list[QuoteTick] = []
        self.trades_seen: list[TradeTick] = []
        self.bars_seen: list[Bar] = []

    async def on_quote(self, quote: QuoteTick) -> None:
        self.quotes_seen.append(quote)

    async def on_trade(self, trade: TradeTick) -> None:
        self.trades_seen.append(trade)

    async def on_bar(self, bar: Bar) -> None:
        self.bars_seen.append(bar)


# ═════════════════════════════════════════════════════════════════════════
# 1. TOPIC-BASED EVENTBUS ROUTING
# ═════════════════════════════════════════════════════════════════════════


class TestTopicBasedEventBus:
    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_topic_specific_subscription_receives_only_matching(self, bus):
        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe("quote", handler, topic="AAPL")
        await bus.publish("quote", {"symbol": "AAPL", "price": 150}, topic="AAPL")
        await bus.publish("quote", {"symbol": "MSFT", "price": 300}, topic="MSFT")

        assert len(received) == 1
        assert received[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_broad_subscription_receives_all_events(self, bus):
        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe("quote", handler)  # no topic = broad
        await bus.publish("quote", {"symbol": "AAPL"}, topic="AAPL")
        await bus.publish("quote", {"symbol": "MSFT"}, topic="MSFT")
        await bus.publish("quote", {"symbol": "GOOGL"})  # no topic

        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_mixed_topic_and_broad_subscriptions(self, bus):
        broad_received = []
        aapl_received = []

        async def broad_handler(ch, ev):
            broad_received.append(ev)

        async def aapl_handler(ch, ev):
            aapl_received.append(ev)

        await bus.subscribe("quote", broad_handler)  # broad
        await bus.subscribe("quote", aapl_handler, topic="AAPL")  # topic-specific

        await bus.publish("quote", {"symbol": "AAPL"}, topic="AAPL")
        await bus.publish("quote", {"symbol": "MSFT"}, topic="MSFT")

        assert len(broad_received) == 2  # broad sees everything
        assert len(aapl_received) == 1  # topic sees only AAPL
        assert aapl_received[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_publish_without_topic_reaches_broad_only(self, bus):
        broad_received = []
        topic_received = []

        async def broad_handler(ch, ev):
            broad_received.append(ev)

        async def topic_handler(ch, ev):
            topic_received.append(ev)

        await bus.subscribe("quote", broad_handler)
        await bus.subscribe("quote", topic_handler, topic="AAPL")

        await bus.publish("quote", {"symbol": "AAPL"})  # no topic

        assert len(broad_received) == 1
        assert len(topic_received) == 0  # topic handler doesn't fire without matching topic

    @pytest.mark.asyncio
    async def test_unsubscribe_with_topic(self, bus):
        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe("quote", handler, topic="AAPL")
        await bus.publish("quote", "first", topic="AAPL")
        await bus.unsubscribe("quote", handler, topic="AAPL")
        await bus.publish("quote", "second", topic="AAPL")

        assert received == ["first"]

    @pytest.mark.asyncio
    async def test_unsubscribe_topic_does_not_affect_broad(self, bus):
        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe("quote", handler)  # broad
        await bus.subscribe("quote", handler, topic="AAPL")  # also topic

        await bus.unsubscribe("quote", handler, topic="AAPL")
        await bus.publish("quote", "msg", topic="AAPL")

        # Broad subscription still active
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_topic_filtered_count_metric(self, bus):
        async def handler(ch, ev):
            pass

        await bus.subscribe("quote", handler, topic="AAPL")
        await bus.publish("quote", "msg", topic="AAPL")
        await bus.publish("quote", "msg", topic="AAPL")

        assert bus.topic_filtered_count == 2

    @pytest.mark.asyncio
    async def test_multiple_topic_subscribers(self, bus):
        aapl = []
        msft = []

        async def aapl_handler(ch, ev):
            aapl.append(ev)

        async def msft_handler(ch, ev):
            msft.append(ev)

        await bus.subscribe("quote", aapl_handler, topic="AAPL")
        await bus.subscribe("quote", msft_handler, topic="MSFT")

        await bus.publish("quote", "aapl_data", topic="AAPL")
        await bus.publish("quote", "msft_data", topic="MSFT")

        assert aapl == ["aapl_data"]
        assert msft == ["msft_data"]

    @pytest.mark.asyncio
    async def test_backward_compat_no_topic(self, bus):
        """Existing code without topics still works."""
        received = []

        async def handler(ch, ev):
            received.append((ch, ev))

        await bus.subscribe("trade", handler)
        await bus.publish("trade", {"data": 1})

        assert len(received) == 1
        assert received[0] == ("trade", {"data": 1})


# ═════════════════════════════════════════════════════════════════════════
# 2. BINARY SERIALIZATION (MSGPACK)
# ═════════════════════════════════════════════════════════════════════════


class TestSerializationModule:
    def test_json_roundtrip(self):
        data = {"symbol": "AAPL", "price": 150.5, "volume": 1000}
        raw = serialize(data, Format.JSON)
        assert isinstance(raw, bytes)
        result = deserialize(raw, Format.JSON)
        assert result == data

    def test_msgpack_roundtrip(self):
        data = {"symbol": "AAPL", "price": 150.5, "volume": 1000}
        raw = serialize(data, Format.MSGPACK)
        assert isinstance(raw, bytes)
        result = deserialize(raw, Format.MSGPACK)
        assert result == data

    def test_msgpack_smaller_than_json(self):
        data = {"symbol": "AAPL", "bid": 150.0, "ask": 150.05, "size": 100}
        json_bytes = serialize(data, Format.JSON)
        msgpack_bytes = serialize(data, Format.MSGPACK)
        assert len(msgpack_bytes) < len(json_bytes)

    def test_detect_format_json(self):
        assert detect_format("application/json") == Format.JSON
        assert detect_format(None) == Format.JSON
        assert detect_format("text/plain") == Format.JSON

    def test_detect_format_msgpack(self):
        assert detect_format("application/x-msgpack") == Format.MSGPACK
        assert detect_format("application/msgpack") == Format.MSGPACK

    def test_has_msgpack(self):
        assert has_msgpack() is True

    def test_bar_roundtrip_msgpack(self):
        bar_data = {
            "symbol": "AAPL",
            "open": 185.0,
            "high": 186.0,
            "low": 184.5,
            "close": 185.5,
            "volume": 10000,
            "timestamp": "2024-01-15T09:30:00",
        }
        raw = serialize(bar_data, Format.MSGPACK)
        result = deserialize(raw, Format.MSGPACK)
        assert result["symbol"] == "AAPL"
        assert result["close"] == 185.5

    def test_quote_roundtrip_msgpack(self):
        quote_data = {
            "symbol": "AAPL",
            "bid_price": 185.0,
            "bid_size": 100,
            "ask_price": 185.5,
            "ask_size": 200,
            "timestamp": "2024-01-15T09:30:00",
        }
        raw = serialize(quote_data, Format.MSGPACK)
        result = deserialize(raw, Format.MSGPACK)
        assert result["symbol"] == "AAPL"
        assert result["bid_price"] == 185.0

    def test_trade_roundtrip_msgpack(self):
        trade_data = {"symbol": "AAPL", "price": 185.25, "size": 100, "timestamp": "2024-01-15T09:30:00"}
        raw = serialize(trade_data, Format.MSGPACK)
        result = deserialize(raw, Format.MSGPACK)
        assert result["price"] == 185.25


class TestIngestionMsgpack:
    @pytest.fixture
    def client(self):
        import asyncio
        from trading_platform.dashboard.app import create_app
        from trading_platform.data.config import DataConfig
        from trading_platform.data.manager import DataManager

        bus = EventBus()
        cfg = DataConfig(max_bars_per_request=5)
        dm = DataManager(bus, config=cfg)
        loop = asyncio.new_event_loop()
        try:
            app, _ = loop.run_until_complete(create_app(bus, data_manager=dm))
        finally:
            loop.close()
        return TestClient(app), dm

    def test_rest_bars_msgpack(self, client):
        tc, dm = client
        bar = {
            "symbol": "AAPL",
            "open": 185.0,
            "high": 186.0,
            "low": 184.5,
            "close": 185.5,
            "volume": 10000,
            "timestamp": "2024-01-15T09:30:00",
        }
        body = serialize(bar, Format.MSGPACK)
        resp = tc.post(
            "/api/data/bars",
            content=body,
            headers={"Content-Type": "application/x-msgpack"},
        )
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1
        assert dm.bars_received == 1

    def test_rest_quotes_msgpack(self, client):
        tc, dm = client
        quote = {
            "symbol": "AAPL",
            "bid_price": 185.0,
            "bid_size": 100,
            "ask_price": 185.5,
            "ask_size": 200,
            "timestamp": "2024-01-15T09:30:00",
        }
        body = serialize(quote, Format.MSGPACK)
        resp = tc.post(
            "/api/data/quotes",
            content=body,
            headers={"Content-Type": "application/x-msgpack"},
        )
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1

    def test_rest_response_msgpack_via_accept(self, client):
        tc, _ = client
        bar = {
            "symbol": "AAPL",
            "open": 185.0,
            "high": 186.0,
            "low": 184.5,
            "close": 185.5,
            "volume": 10000,
            "timestamp": "2024-01-15T09:30:00",
        }
        body = serialize(bar, Format.MSGPACK)
        resp = tc.post(
            "/api/data/bars",
            content=body,
            headers={
                "Content-Type": "application/x-msgpack",
                "Accept": "application/x-msgpack",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/x-msgpack"
        result = deserialize(resp.content, Format.MSGPACK)
        assert result["ingested"] == 1

    def test_rest_json_still_works(self, client):
        tc, dm = client
        bar = {
            "symbol": "AAPL",
            "open": 185.0,
            "high": 186.0,
            "low": 184.5,
            "close": 185.5,
            "volume": 10000,
            "timestamp": "2024-01-15T09:30:00",
        }
        resp = tc.post("/api/data/bars", json=bar)
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1

    def test_ws_binary_frame_msgpack(self, client):
        tc, dm = client
        msg = {
            "type": "bar",
            "data": {
                "symbol": "AAPL",
                "open": 185.0,
                "high": 186.0,
                "low": 184.5,
                "close": 185.5,
                "volume": 10000,
                "timestamp": "2024-01-15T09:30:00",
            },
        }
        packed = serialize(msg, Format.MSGPACK)
        # Single-message ingestion uses fire-and-forget (no ack on success)
        with tc.websocket_connect("/ws/data") as ws:
            ws.send_bytes(packed)
        assert dm.bars_received == 1

    def test_ws_text_frame_json_still_works(self, client):
        tc, dm = client
        msg = {
            "type": "bar",
            "data": {
                "symbol": "AAPL",
                "open": 185.0,
                "high": 186.0,
                "low": 184.5,
                "close": 185.5,
                "volume": 10000,
                "timestamp": "2024-01-15T09:30:00",
            },
        }
        # Single-message ingestion uses fire-and-forget (no ack on success)
        with tc.websocket_connect("/ws/data") as ws:
            ws.send_text(json.dumps(msg))
        assert dm.bars_received == 1

    def test_ws_batch_binary_msgpack(self, client):
        tc, dm = client
        batch = [
            {
                "type": "bar",
                "data": {
                    "symbol": "AAPL",
                    "open": 185.0,
                    "high": 186.0,
                    "low": 184.5,
                    "close": 185.5,
                    "volume": 10000,
                    "timestamp": "2024-01-15T09:30:00",
                },
            },
            {
                "type": "trade",
                "data": {
                    "symbol": "AAPL",
                    "price": 185.25,
                    "size": 100,
                    "timestamp": "2024-01-15T09:30:00",
                },
            },
        ]
        packed = serialize(batch, Format.MSGPACK)
        with tc.websocket_connect("/ws/data") as ws:
            ws.send_bytes(packed)
            resp_bytes = ws.receive_bytes()
            resp = deserialize(resp_bytes, Format.MSGPACK)
            assert resp["batch"] is True
            assert len(resp["results"]) == 2


class TestLazyDeserialization:
    @pytest.mark.asyncio
    async def test_enqueue_raw_lazy_stores_bytes(self):
        mq = MessageQueue(max_size=10, mode="lossy", dedup_quotes=False, lazy_deserialize=True)
        data = {"symbol": "AAPL", "price": 150.0}
        raw = serialize(data, Format.JSON)

        result = await mq.enqueue_raw(raw, "json")
        assert result is True
        assert mq.enqueue_count == 1
        assert mq.depth == 1

        # Peek at the raw item — it should be a tuple
        item = mq._queue.get_nowait()
        assert isinstance(item, tuple)
        assert isinstance(item[0], bytes)
        assert item[1] == "json"

    @pytest.mark.asyncio
    async def test_enqueue_raw_lazy_msgpack(self):
        mq = MessageQueue(max_size=10, mode="lossy", dedup_quotes=False, lazy_deserialize=True)
        data = {"symbol": "AAPL", "price": 150.0}
        raw = serialize(data, Format.MSGPACK)

        await mq.enqueue_raw(raw, "msgpack")
        item = mq._queue.get_nowait()
        assert isinstance(item, tuple)
        assert item[1] == "msgpack"

    @pytest.mark.asyncio
    async def test_lazy_deser_consumer_resolves(self):
        mq = MessageQueue(max_size=100, mode="lossy", dedup_quotes=False, lazy_deserialize=True)
        received: list[list] = []

        async def callback(batch):
            received.append(list(batch))

        data = {"symbol": "AAPL", "price": 150.0}
        raw = serialize(data, Format.JSON)
        await mq.enqueue_raw(raw, "json")

        mq.start_consumer(callback, batch_size=10, flush_interval_ms=20)
        await asyncio.sleep(0.1)
        await mq.stop()

        assert len(received) >= 1
        all_items = [item for batch in received for item in batch]
        assert len(all_items) == 1
        assert all_items[0]["symbol"] == "AAPL"
        assert all_items[0]["price"] == 150.0

    @pytest.mark.asyncio
    async def test_enqueue_raw_eager_when_disabled(self):
        mq = MessageQueue(max_size=10, mode="lossy", dedup_quotes=False, lazy_deserialize=False)
        data = {"symbol": "AAPL", "price": 150.0}
        raw = serialize(data, Format.JSON)

        await mq.enqueue_raw(raw, "json")
        # When lazy_deserialize is False, should be stored as dict
        item = mq._queue.get_nowait()
        assert isinstance(item, dict)
        assert item["symbol"] == "AAPL"

    def test_resolve_item_dict_passthrough(self):
        mq = MessageQueue(max_size=10, mode="lossy")
        data = {"symbol": "AAPL"}
        assert mq._resolve_item(data) == data

    def test_resolve_item_bytes_tuple(self):
        mq = MessageQueue(max_size=10, mode="lossy")
        data = {"symbol": "AAPL", "price": 150.0}
        raw = serialize(data, Format.JSON)
        result = mq._resolve_item((raw, "json"))
        assert result["symbol"] == "AAPL"

    def test_resolve_item_msgpack_tuple(self):
        mq = MessageQueue(max_size=10, mode="lossy")
        data = {"symbol": "AAPL", "price": 150.0}
        raw = serialize(data, Format.MSGPACK)
        result = mq._resolve_item((raw, "msgpack"))
        assert result["symbol"] == "AAPL"


# ═════════════════════════════════════════════════════════════════════════
# 3. CONNECTION POOLING
# ═════════════════════════════════════════════════════════════════════════


class TestConnectionPooling:
    @pytest.mark.asyncio
    async def test_public_com_client_pool_configured(self):
        """After connect, the SDK's httpx client should have pool limits."""
        from trading_platform.adapters.public_com.client import PublicComClient, _POOL_LIMITS, _TIMEOUT
        from trading_platform.adapters.public_com.config import PublicComConfig

        config = PublicComConfig(api_secret="test-secret", account_id="test-acc")
        client = PublicComClient(config)

        # Mock the SDK to avoid real network calls
        with patch("trading_platform.adapters.public_com.client.AsyncPublicApiClient") as MockSDK:
            mock_sdk = MagicMock()
            mock_api_client = MagicMock()
            mock_httpx = MagicMock()
            mock_httpx.headers = {"Authorization": "Bearer test"}
            mock_api_client._client = mock_httpx
            mock_sdk.api_client = mock_api_client
            mock_sdk.__aenter__ = AsyncMock(return_value=mock_sdk)
            MockSDK.return_value = mock_sdk

            with patch("trading_platform.adapters.public_com.client.httpx.AsyncClient") as MockHttpx:
                mock_new_client = MagicMock()
                MockHttpx.return_value = mock_new_client

                await client.connect()

                MockHttpx.assert_called_once_with(
                    headers={"Authorization": "Bearer test"},
                    limits=_POOL_LIMITS,
                    timeout=_TIMEOUT,
                )
                assert mock_sdk.api_client._client is mock_new_client

    @pytest.mark.asyncio
    async def test_public_com_client_disconnect_cleanup(self):
        from trading_platform.adapters.public_com.client import PublicComClient
        from trading_platform.adapters.public_com.config import PublicComConfig

        config = PublicComConfig(api_secret="test", account_id="acc")
        client = PublicComClient(config)

        mock_sdk = MagicMock()
        mock_sdk.__aexit__ = AsyncMock()
        client._client = mock_sdk

        await client.disconnect()
        mock_sdk.__aexit__.assert_awaited_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_crypto_client_pool_configured(self):
        """Verify the crypto client also configures pool limits."""
        from trading_platform.adapters.crypto.client import CryptoClient, _POOL_LIMITS, _TIMEOUT
        from trading_platform.adapters.crypto.config import CryptoConfig

        config = CryptoConfig(api_secret="test-secret", account_id="test-acc")
        client = CryptoClient(config)

        with patch("trading_platform.adapters.crypto.client.AsyncPublicApiClient") as MockSDK:
            mock_sdk = MagicMock()
            mock_api_client = MagicMock()
            mock_httpx = MagicMock()
            mock_httpx.headers = {"Authorization": "Bearer test"}
            mock_api_client._client = mock_httpx
            mock_sdk.api_client = mock_api_client
            mock_sdk.__aenter__ = AsyncMock(return_value=mock_sdk)
            MockSDK.return_value = mock_sdk

            with patch("trading_platform.adapters.crypto.client.httpx.AsyncClient") as MockHttpx:
                mock_new_client = MagicMock()
                MockHttpx.return_value = mock_new_client

                await client.connect()

                MockHttpx.assert_called_once_with(
                    headers={"Authorization": "Bearer test"},
                    limits=_POOL_LIMITS,
                    timeout=_TIMEOUT,
                )

    @pytest.mark.asyncio
    async def test_options_client_pool_configured(self):
        """Verify the options client also configures pool limits."""
        from trading_platform.adapters.options.client import OptionsClient, _POOL_LIMITS, _TIMEOUT
        from trading_platform.adapters.options.config import OptionsConfig

        config = OptionsConfig(api_secret="test-secret", account_id="test-acc")
        client = OptionsClient(config)

        with patch("trading_platform.adapters.options.client.AsyncPublicApiClient") as MockSDK:
            mock_sdk = MagicMock()
            mock_api_client = MagicMock()
            mock_httpx = MagicMock()
            mock_httpx.headers = {"Authorization": "Bearer test"}
            mock_api_client._client = mock_httpx
            mock_sdk.api_client = mock_api_client
            mock_sdk.__aenter__ = AsyncMock(return_value=mock_sdk)
            MockSDK.return_value = mock_sdk

            with patch("trading_platform.adapters.options.client.httpx.AsyncClient") as MockHttpx:
                mock_new_client = MagicMock()
                MockHttpx.return_value = mock_new_client

                await client.connect()

                MockHttpx.assert_called_once_with(
                    headers={"Authorization": "Bearer test"},
                    limits=_POOL_LIMITS,
                    timeout=_TIMEOUT,
                )

    def test_pool_limits_values(self):
        from trading_platform.adapters.public_com.client import _POOL_LIMITS, _TIMEOUT

        assert _POOL_LIMITS.max_connections == 20
        assert _POOL_LIMITS.max_keepalive_connections == 10
        assert _TIMEOUT.connect == 10.0


# ═════════════════════════════════════════════════════════════════════════
# 4. CONDITIONAL STRATEGY EVALUATION
# ═════════════════════════════════════════════════════════════════════════


class TestConditionalEvaluation:
    @pytest.fixture
    def bus(self):
        return EventBus()

    # ── Strategy base class gate tests ────────────────────────────────

    def test_default_no_gate_always_evaluates(self, bus):
        s = DummyStrategy("s1", bus)
        assert s._should_evaluate("AAPL", Decimal("150")) is True
        s._record_evaluation("AAPL", Decimal("150"))
        assert s._should_evaluate("AAPL", Decimal("150.01")) is True

    def test_min_price_change_gate_skips_below_threshold(self, bus):
        s = DummyStrategy("s1", bus, config={"min_price_change": "1.0"})
        assert s.min_price_change == Decimal("1.0")

        # First tick always evaluates
        assert s._should_evaluate("AAPL", Decimal("150")) is True
        s._record_evaluation("AAPL", Decimal("150"))

        # Small change — skip
        assert s._should_evaluate("AAPL", Decimal("150.50")) is False

        # Large change — evaluate
        assert s._should_evaluate("AAPL", Decimal("151.50")) is True

    def test_min_price_change_percent_gate(self, bus):
        s = DummyStrategy("s1", bus, config={"min_price_change_percent": "0.01"})  # 1%
        assert s.min_price_change_percent == Decimal("0.01")

        assert s._should_evaluate("AAPL", Decimal("100")) is True
        s._record_evaluation("AAPL", Decimal("100"))

        # 0.5% change — skip
        assert s._should_evaluate("AAPL", Decimal("100.50")) is False

        # 1.5% change — evaluate
        assert s._should_evaluate("AAPL", Decimal("101.50")) is True

    def test_either_gate_sufficient(self, bus):
        s = DummyStrategy("s1", bus, config={
            "min_price_change": "2.0",
            "min_price_change_percent": "0.01",
        })
        assert s._should_evaluate("AAPL", Decimal("100")) is True
        s._record_evaluation("AAPL", Decimal("100"))

        # Abs change of 1.5 < 2.0, but pct = 1.5% > 1%
        assert s._should_evaluate("AAPL", Decimal("101.50")) is True

    def test_first_tick_always_evaluates(self, bus):
        s = DummyStrategy("s1", bus, config={"min_price_change": "100"})
        # Even with a huge threshold, first tick always evaluates
        assert s._should_evaluate("AAPL", Decimal("150")) is True

    def test_per_symbol_tracking(self, bus):
        s = DummyStrategy("s1", bus, config={"min_price_change": "1.0"})

        # First tick for AAPL
        assert s._should_evaluate("AAPL", Decimal("150")) is True
        s._record_evaluation("AAPL", Decimal("150"))

        # First tick for MSFT (independent of AAPL)
        assert s._should_evaluate("MSFT", Decimal("300")) is True
        s._record_evaluation("MSFT", Decimal("300"))

        # Small AAPL move — skip
        assert s._should_evaluate("AAPL", Decimal("150.50")) is False

        # Large MSFT move — evaluate
        assert s._should_evaluate("MSFT", Decimal("302")) is True

    def test_skip_rate_percent(self, bus):
        s = DummyStrategy("s1", bus, config={"min_price_change": "1.0"})
        assert s.skip_rate_percent == 0.0

        s.evaluations_run = 3
        s.evaluations_skipped = 7
        assert s.skip_rate_percent == 70.0

    def test_record_evaluation_updates_last_price(self, bus):
        s = DummyStrategy("s1", bus)
        s._record_evaluation("AAPL", Decimal("150"))
        assert s._last_eval_prices["AAPL"] == Decimal("150")
        assert s.evaluations_run == 1

    # ── StrategyManager dispatch with gate ────────────────────────────

    @pytest.mark.asyncio
    async def test_dispatch_quote_skips_below_threshold(self, bus):
        s = DummyStrategy("gated", bus, config={"min_price_change": "1.0"})
        sm = StrategyManager(bus)
        sm.register(s)
        await sm.start_strategy("gated")

        # First quote — always evaluates
        await sm.dispatch_quote("quote", _make_quote("AAPL", bid=150.0))
        assert len(s.quotes_seen) == 1

        # Small move — skip
        await sm.dispatch_quote("quote", _make_quote("AAPL", bid=150.10))
        assert len(s.quotes_seen) == 1  # still 1
        assert s.evaluations_skipped == 1

        # Large move — evaluate
        await sm.dispatch_quote("quote", _make_quote("AAPL", bid=151.50))
        assert len(s.quotes_seen) == 2

    @pytest.mark.asyncio
    async def test_dispatch_trade_skips_below_threshold(self, bus):
        s = DummyStrategy("gated", bus, config={"min_price_change": "1.0"})
        sm = StrategyManager(bus)
        sm.register(s)
        await sm.start_strategy("gated")

        await sm.dispatch_trade("trade", _make_trade("AAPL", price=150.0))
        assert len(s.trades_seen) == 1

        await sm.dispatch_trade("trade", _make_trade("AAPL", price=150.10))
        assert len(s.trades_seen) == 1
        assert s.evaluations_skipped == 1

    @pytest.mark.asyncio
    async def test_dispatch_bar_skips_below_threshold(self, bus):
        s = DummyStrategy("gated", bus, config={"min_price_change": "1.0"})
        sm = StrategyManager(bus)
        sm.register(s)
        await sm.start_strategy("gated")

        await sm.dispatch_bar("bar", _make_bar("AAPL", close=150.0))
        assert len(s.bars_seen) == 1

        await sm.dispatch_bar("bar", _make_bar("AAPL", close=150.10))
        assert len(s.bars_seen) == 1

    @pytest.mark.asyncio
    async def test_no_gate_default_evaluates_everything(self, bus):
        s = DummyStrategy("no_gate", bus)
        sm = StrategyManager(bus)
        sm.register(s)
        await sm.start_strategy("no_gate")

        for i in range(5):
            await sm.dispatch_quote("quote", _make_quote("AAPL", bid=150.0 + i * 0.01))
        assert len(s.quotes_seen) == 5
        assert s.evaluations_skipped == 0

    @pytest.mark.asyncio
    async def test_bracket_not_affected_by_gate(self, bus):
        """Bracket orders use their own quote handlers, not strategy evaluation gate."""
        from trading_platform.bracket.manager import BracketOrderManager

        exec_mock = AsyncMock()
        exec_mock.submit_order = AsyncMock(return_value={"order_id": "mock-123"})
        bm = BracketOrderManager(event_bus=bus, exec_adapter=exec_mock)

        # BracketOrderManager subscribes to quote events via topic-specific subs
        # It doesn't go through strategy evaluation gate — it handles every tick
        # Verify the class doesn't have _should_evaluate
        assert not hasattr(bm, "_should_evaluate")

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, bus):
        s = DummyStrategy("gated", bus, config={"min_price_change": "1.0"})
        sm = StrategyManager(bus)
        sm.register(s)
        await sm.start_strategy("gated")

        # First tick evaluates
        await sm.dispatch_quote("quote", _make_quote("AAPL", bid=150.0))
        assert s.evaluations_run == 1
        assert s.evaluations_skipped == 0

        # Small ticks skipped
        await sm.dispatch_quote("quote", _make_quote("AAPL", bid=150.10))
        await sm.dispatch_quote("quote", _make_quote("AAPL", bid=150.20))
        assert s.evaluations_run == 1
        assert s.evaluations_skipped == 2
        assert s.skip_rate_percent == pytest.approx(66.67, abs=0.1)
