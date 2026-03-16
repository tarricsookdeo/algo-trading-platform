"""Tests for the OrderRouter."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.core.enums import AssetClass, ContractType, OrderSide, OrderType
from trading_platform.core.models import MultiLegOrder, Order, Position
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


# ── Options-specific routing ─────────────────────────────────────────


@pytest.fixture
def options_adapter():
    adapter = AsyncMock()
    adapter.submit_order = AsyncMock(return_value={"id": "opt-1"})
    adapter.submit_multileg_order = AsyncMock(return_value={"id": "ml-1"})
    adapter.cancel_order = AsyncMock(return_value=None)
    adapter.cancel_option_order = AsyncMock(return_value=None)
    adapter.get_positions = AsyncMock(return_value=[])
    adapter.get_option_positions = AsyncMock(
        return_value=[Position(symbol="AAPL240119C00150000", quantity=Decimal("5"))]
    )
    adapter.get_account = AsyncMock(return_value={"option_buying_power": 20_000})
    adapter.preflight_option_order = AsyncMock(return_value={"buying_power_effect": -500.0})
    adapter.get_option_chain = AsyncMock(return_value={"calls": [], "puts": []})
    adapter.get_option_expirations = AsyncMock(return_value=["2024-01-19", "2024-02-16"])
    return adapter


@pytest.fixture
def options_router(equity_adapter, options_adapter):
    r = OrderRouter()
    r.register(AssetClass.EQUITY, equity_adapter)
    r.register(AssetClass.OPTION, options_adapter)
    return r


def _option_order(**kwargs) -> Order:
    defaults = dict(
        symbol="AAPL240119C00150000",
        option_symbol="AAPL240119C00150000",
        asset_class=AssetClass.OPTION,
        contract_type=ContractType.CALL,
        strike_price=Decimal("150"),
        expiration_date="2024-01-19",
        underlying_symbol="AAPL",
        quantity=Decimal("1"),
    )
    defaults.update(kwargs)
    return Order(**defaults)


def _two_leg_order() -> MultiLegOrder:
    buy = _option_order(side=OrderSide.BUY)
    sell = _option_order(side=OrderSide.SELL, strike_price=Decimal("155"))
    return MultiLegOrder(legs=[buy, sell], strategy_type="vertical_spread")


class TestOptionsRouting:
    def test_get_options_adapter_raises_when_not_registered(self):
        r = OrderRouter()
        with pytest.raises(ValueError, match="No adapter registered for asset class 'option'"):
            r._get_options_adapter()

    def test_get_options_adapter_returns_registered_adapter(self, options_router, options_adapter):
        assert options_router._get_options_adapter() is options_adapter

    @pytest.mark.asyncio
    async def test_submit_multileg_order_routes_to_options_adapter(
        self, options_router, options_adapter
    ):
        result = await options_router.submit_multileg_order(_two_leg_order())
        options_adapter.submit_multileg_order.assert_awaited_once()
        assert result == {"id": "ml-1"}

    @pytest.mark.asyncio
    async def test_submit_multileg_raises_if_no_options_adapter(self):
        r = OrderRouter()
        with pytest.raises(ValueError, match="No adapter registered"):
            await r.submit_multileg_order(_two_leg_order())

    @pytest.mark.asyncio
    async def test_cancel_option_order_routes_to_options_adapter(
        self, options_router, options_adapter
    ):
        await options_router.cancel_option_order("opt-abc")
        options_adapter.cancel_option_order.assert_awaited_once_with("opt-abc")

    @pytest.mark.asyncio
    async def test_cancel_option_order_raises_if_no_options_adapter(self):
        r = OrderRouter()
        with pytest.raises(ValueError, match="No adapter registered"):
            await r.cancel_option_order("opt-abc")

    @pytest.mark.asyncio
    async def test_get_option_positions(self, options_router, options_adapter):
        positions = await options_router.get_option_positions()
        options_adapter.get_option_positions.assert_awaited_once()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL240119C00150000"

    @pytest.mark.asyncio
    async def test_preflight_option_order(self, options_router, options_adapter):
        order = _option_order(order_type=OrderType.LIMIT, limit_price=5.00)
        result = await options_router.preflight_option_order(order)
        options_adapter.preflight_option_order.assert_awaited_once_with(order)
        assert result == {"buying_power_effect": -500.0}

    @pytest.mark.asyncio
    async def test_get_option_chain(self, options_router, options_adapter):
        result = await options_router.get_option_chain("AAPL")
        options_adapter.get_option_chain.assert_awaited_once_with("AAPL")
        assert result == {"calls": [], "puts": []}

    @pytest.mark.asyncio
    async def test_get_option_expirations(self, options_router, options_adapter):
        result = await options_router.get_option_expirations("AAPL")
        options_adapter.get_option_expirations.assert_awaited_once_with("AAPL")
        assert result == ["2024-01-19", "2024-02-16"]
