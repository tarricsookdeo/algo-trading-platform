"""Tests for the OrderRouter."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.core.enums import AssetClass, OrderSide, OrderType
from trading_platform.core.models import Order, Position
from trading_platform.core.order_router import OrderRouter


@pytest.fixture
def equity_adapter():
    adapter = AsyncMock()
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    adapter.submit_order = AsyncMock(return_value={"id": "eq-1"})
    adapter.cancel_order = AsyncMock(return_value=None)
    adapter.get_positions = AsyncMock(return_value=[
        Position(symbol="AAPL", quantity=Decimal("10")),
    ])
    adapter.get_account = AsyncMock(return_value={"equity": 100_000})
    return adapter


@pytest.fixture
def crypto_adapter():
    adapter = AsyncMock()
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    adapter.submit_order = AsyncMock(return_value={"id": "cr-1"})
    adapter.cancel_order = AsyncMock(return_value=None)
    adapter.get_positions = AsyncMock(return_value=[
        Position(symbol="BTC-USD", quantity=Decimal("0.5")),
    ])
    adapter.get_account = AsyncMock(return_value={"balance": 50_000})
    return adapter


@pytest.fixture
def router(equity_adapter, crypto_adapter):
    r = OrderRouter()
    r.register(AssetClass.EQUITY, equity_adapter)
    r.register(AssetClass.CRYPTO, crypto_adapter)
    return r


class TestRegister:
    def test_register_and_get(self, equity_adapter):
        r = OrderRouter()
        r.register(AssetClass.EQUITY, equity_adapter)
        assert r.get_adapter(AssetClass.EQUITY) is equity_adapter

    def test_get_unregistered(self):
        r = OrderRouter()
        assert r.get_adapter(AssetClass.CRYPTO) is None

    def test_overwrite_registration(self, equity_adapter, crypto_adapter):
        r = OrderRouter()
        r.register(AssetClass.EQUITY, equity_adapter)
        r.register(AssetClass.EQUITY, crypto_adapter)
        assert r.get_adapter(AssetClass.EQUITY) is crypto_adapter


class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_routes_equity(self, router, equity_adapter):
        order = Order(symbol="AAPL", asset_class=AssetClass.EQUITY, quantity=Decimal("10"))
        result = await router.submit_order(order)
        equity_adapter.submit_order.assert_awaited_once_with(order)
        assert result == {"id": "eq-1"}

    @pytest.mark.asyncio
    async def test_routes_crypto(self, router, crypto_adapter):
        order = Order(symbol="BTC-USD", asset_class=AssetClass.CRYPTO, quantity=Decimal("0.1"))
        result = await router.submit_order(order)
        crypto_adapter.submit_order.assert_awaited_once_with(order)
        assert result == {"id": "cr-1"}

    @pytest.mark.asyncio
    async def test_no_adapter_raises(self):
        r = OrderRouter()
        order = Order(symbol="AAPL", asset_class=AssetClass.EQUITY)
        with pytest.raises(ValueError, match="No adapter registered"):
            await r.submit_order(order)

    @pytest.mark.asyncio
    async def test_default_asset_class_is_equity(self, router, equity_adapter):
        order = Order(symbol="SPY", quantity=Decimal("5"))
        await router.submit_order(order)
        equity_adapter.submit_order.assert_awaited_once()


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_found(self, router, equity_adapter):
        await router.cancel_order("eq-1")
        equity_adapter.cancel_order.assert_awaited()

    @pytest.mark.asyncio
    async def test_cancel_tries_all(self, router, equity_adapter, crypto_adapter):
        equity_adapter.cancel_order = AsyncMock(side_effect=Exception("not found"))
        await router.cancel_order("cr-1")
        crypto_adapter.cancel_order.assert_awaited_once_with("cr-1")

    @pytest.mark.asyncio
    async def test_cancel_none_found(self, equity_adapter, crypto_adapter):
        r = OrderRouter()
        r.register(AssetClass.EQUITY, equity_adapter)
        r.register(AssetClass.CRYPTO, crypto_adapter)
        equity_adapter.cancel_order = AsyncMock(side_effect=Exception("nope"))
        crypto_adapter.cancel_order = AsyncMock(side_effect=Exception("nope"))
        with pytest.raises(ValueError, match="No adapter could cancel"):
            await r.cancel_order("unknown-id")


class TestGetPositions:
    @pytest.mark.asyncio
    async def test_aggregates_all(self, router):
        positions = await router.get_positions()
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"AAPL", "BTC-USD"}

    @pytest.mark.asyncio
    async def test_empty_router(self):
        r = OrderRouter()
        assert await r.get_positions() == []


class TestGetAccount:
    @pytest.mark.asyncio
    async def test_aggregates_accounts(self, router):
        account = await router.get_account()
        assert "equity" in account
        assert "crypto" in account
        assert account["equity"] == {"equity": 100_000}
        assert account["crypto"] == {"balance": 50_000}


class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_all(self, router, equity_adapter, crypto_adapter):
        await router.connect()
        equity_adapter.connect.assert_awaited_once()
        crypto_adapter.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_all(self, router, equity_adapter, crypto_adapter):
        await router.disconnect()
        equity_adapter.disconnect.assert_awaited_once()
        crypto_adapter.disconnect.assert_awaited_once()
