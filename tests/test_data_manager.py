"""Tests for DataManager — registration, start/stop, event publishing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, PropertyMock

import pytest

from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.data.config import DataConfig
from trading_platform.data.manager import DataManager
from trading_platform.data.provider import DataProvider


# ── Helpers ──────────────────────────────────────────────────────────


class StubProvider(DataProvider):
    """Minimal concrete provider for testing."""

    def __init__(self, provider_name: str = "stub") -> None:
        self._name = provider_name
        self._connected = False

    @property
    def name(self) -> str:
        return self._name

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


# ── Tests ────────────────────────────────────────────────────────────


class TestRegistration:
    def test_register_provider(self):
        bus = EventBus()
        dm = DataManager(bus)
        prov = StubProvider("test_prov")
        dm.register_provider(prov)
        status = dm.get_provider_status()
        assert len(status) == 1
        assert status[0]["name"] == "test_prov"
        assert status[0]["connected"] is False

    def test_register_multiple_providers(self):
        bus = EventBus()
        dm = DataManager(bus)
        dm.register_provider(StubProvider("a"))
        dm.register_provider(StubProvider("b"))
        assert len(dm.get_provider_status()) == 2


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_connects_providers(self):
        bus = EventBus()
        dm = DataManager(bus)
        prov = StubProvider("s1")
        dm.register_provider(prov)
        await dm.start()
        assert prov.is_connected is True
        await dm.stop()
        assert prov.is_connected is False

    @pytest.mark.asyncio
    async def test_start_skips_failed_provider(self):
        bus = EventBus()
        dm = DataManager(bus)

        bad = StubProvider("bad")
        bad.connect = AsyncMock(side_effect=RuntimeError("fail"))
        bad._connected = False
        type(bad).is_connected = PropertyMock(return_value=False)

        dm.register_provider(bad)
        # Should not raise
        await dm.start()
        await dm.stop()


class TestIngestionStats:
    def test_initial_stats(self):
        bus = EventBus()
        dm = DataManager(bus)
        stats = dm.get_ingestion_stats()
        assert stats["bars_received"] == 0
        assert stats["quotes_received"] == 0
        assert stats["trades_received"] == 0
        assert stats["providers"] == 0

    @pytest.mark.asyncio
    async def test_publish_bar_increments(self):
        bus = EventBus()
        received = []

        async def on_bar(ch, data):
            received.append(data)

        await bus.subscribe(Channel.BAR, on_bar)

        dm = DataManager(bus)
        bar_data = {"symbol": "AAPL", "close": 185.0}
        await dm.publish_bar(bar_data)

        assert dm.bars_received == 1
        assert len(received) == 1
        assert received[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_publish_quote_increments(self):
        bus = EventBus()
        received = []

        async def on_quote(ch, data):
            received.append(data)

        await bus.subscribe(Channel.QUOTE, on_quote)

        dm = DataManager(bus)
        await dm.publish_quote({"symbol": "MSFT", "bid_price": 380.0})

        assert dm.quotes_received == 1
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_publish_trade_increments(self):
        bus = EventBus()
        received = []

        async def on_trade(ch, data):
            received.append(data)

        await bus.subscribe(Channel.TRADE, on_trade)

        dm = DataManager(bus)
        await dm.publish_trade({"symbol": "TSLA", "price": 250.0})

        assert dm.trades_received == 1
        assert len(received) == 1


class TestConfig:
    def test_default_config(self):
        bus = EventBus()
        dm = DataManager(bus)
        assert dm._config.ingestion_enabled is True
        assert dm._config.max_bars_per_request == 10000

    def test_custom_config(self):
        bus = EventBus()
        cfg = DataConfig(max_bars_per_request=100)
        dm = DataManager(bus, config=cfg)
        assert dm._config.max_bars_per_request == 100
