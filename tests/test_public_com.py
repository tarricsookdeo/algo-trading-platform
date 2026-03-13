"""Tests for Phase 3: Public.com execution adapter (config, parse, adapter)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_platform.adapters.public_com.config import PublicComConfig
from trading_platform.adapters.public_com.parse import (
    map_order_status,
    sdk_order_to_platform,
    sdk_position_to_platform,
)
from trading_platform.core.enums import OrderSide, OrderStatus, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Order


# ── Config tests ──────────────────────────────────────────────────────


class TestPublicComConfig:
    def test_defaults(self):
        c = PublicComConfig()
        assert c.api_secret == ""
        assert c.account_id == ""
        assert c.poll_interval == 2.0
        assert c.portfolio_refresh == 30.0

    def test_custom(self):
        c = PublicComConfig(api_secret="s3cr3t", account_id="acc-123", poll_interval=5.0)
        assert c.api_secret == "s3cr3t"
        assert c.account_id == "acc-123"
        assert c.poll_interval == 5.0


# ── Parse tests ───────────────────────────────────────────────────────


class TestMapOrderStatus:
    def test_filled(self):
        status = SimpleNamespace(name="FILLED")
        assert map_order_status(status) == OrderStatus.FILLED

    def test_cancelled(self):
        status = SimpleNamespace(name="CANCELLED")
        assert map_order_status(status) == OrderStatus.CANCELED

    def test_new(self):
        status = SimpleNamespace(name="NEW")
        assert map_order_status(status) == OrderStatus.NEW

    def test_unknown_defaults_to_new(self):
        status = SimpleNamespace(name="WEIRD_STATUS")
        assert map_order_status(status) == OrderStatus.NEW

    def test_string_input(self):
        assert map_order_status("FILLED") == OrderStatus.FILLED

    def test_rejected(self):
        status = SimpleNamespace(name="REJECTED")
        assert map_order_status(status) == OrderStatus.REJECTED

    def test_expired(self):
        status = SimpleNamespace(name="EXPIRED")
        assert map_order_status(status) == OrderStatus.EXPIRED

    def test_replaced(self):
        status = SimpleNamespace(name="REPLACED")
        assert map_order_status(status) == OrderStatus.CANCELED


class TestSdkOrderToPlatform:
    def test_full_order(self):
        sdk_order = SimpleNamespace(
            order_id="order-abc",
            status=SimpleNamespace(name="FILLED"),
            order_side=SimpleNamespace(name="BUY"),
            order_type=SimpleNamespace(name="LIMIT"),
            instrument=SimpleNamespace(symbol="AAPL"),
            quantity=100,
            limit_price=150.0,
            stop_price=None,
            filled_quantity=100,
            average_fill_price=149.95,
            created_at=datetime(2024, 1, 15, tzinfo=UTC),
            updated_at=datetime(2024, 1, 15, tzinfo=UTC),
        )
        order = sdk_order_to_platform(sdk_order)
        assert order.order_id == "order-abc"
        assert order.status == OrderStatus.FILLED
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.symbol == "AAPL"
        assert order.quantity == Decimal("100")
        assert order.filled_quantity == Decimal("100")

    def test_minimal_order(self):
        sdk_order = SimpleNamespace(
            order_id="o1",
            status=SimpleNamespace(name="NEW"),
            order_side=None,
            order_type=None,
            instrument=None,
            quantity=0,
            limit_price=None,
            stop_price=None,
            filled_quantity=0,
            average_fill_price=0,
            created_at=None,
            updated_at=None,
        )
        order = sdk_order_to_platform(sdk_order)
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.symbol == ""

    def test_sell_stop_limit(self):
        sdk_order = SimpleNamespace(
            order_id="o2",
            status=SimpleNamespace(name="NEW"),
            order_side=SimpleNamespace(name="SELL"),
            order_type=SimpleNamespace(name="STOP_LIMIT"),
            instrument=SimpleNamespace(symbol="MSFT"),
            quantity=50,
            limit_price=400.0,
            stop_price=395.0,
            filled_quantity=0,
            average_fill_price=0,
            created_at=None,
            updated_at=None,
        )
        order = sdk_order_to_platform(sdk_order)
        assert order.side == OrderSide.SELL
        assert order.order_type == OrderType.STOP_LIMIT


class TestSdkPositionToPlatform:
    def test_long_position(self):
        sdk_pos = SimpleNamespace(
            symbol="AAPL",
            quantity=100,
            average_price=150.0,
            market_value=15500.0,
            unrealized_pnl=500.0,
        )
        pos = sdk_position_to_platform(sdk_pos)
        assert pos.symbol == "AAPL"
        assert pos.quantity == Decimal("100")
        assert pos.avg_entry_price == 150.0
        assert pos.market_value == 15500.0
        assert pos.unrealized_pnl == 500.0
        assert pos.side == "long"

    def test_short_position(self):
        sdk_pos = SimpleNamespace(
            symbol="TSLA",
            quantity=-50,
            average_price=200.0,
            market_value=9500.0,
            unrealized_pnl=500.0,
        )
        pos = sdk_position_to_platform(sdk_pos)
        assert pos.quantity == Decimal("50")  # absolute value
        assert pos.side == "short"

    def test_missing_fields(self):
        sdk_pos = SimpleNamespace(symbol="X")
        pos = sdk_position_to_platform(sdk_pos)
        assert pos.symbol == "X"
        assert pos.quantity == Decimal("0")


# ── Adapter tests (with mocked client) ───────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_client():
    """Create a mock PublicComClient."""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.place_order = AsyncMock()
    client.cancel_order = AsyncMock()
    client.get_portfolio = AsyncMock()
    return client


@pytest.fixture
def adapter(bus, mock_client):
    """Create PublicComExecAdapter with mocked client."""
    from trading_platform.adapters.public_com.adapter import PublicComExecAdapter

    config = PublicComConfig(api_secret="test", account_id="acc-1")
    adp = PublicComExecAdapter(config, bus)
    adp._client = mock_client
    return adp


@pytest.mark.asyncio
async def test_adapter_submit_order(adapter, mock_client, bus):
    """Test order submission flow."""
    mock_async_order = AsyncMock()
    mock_async_order.subscribe_updates = AsyncMock()
    mock_async_order.wait_for_terminal_status = AsyncMock()
    mock_client.place_order.return_value = mock_async_order

    received = []

    async def handler(ch, ev):
        received.append(ch)

    await bus.subscribe("execution.order.submitted", handler)

    order = Order(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100.0,
    )
    result = await adapter.submit_order(order)
    assert result is mock_async_order
    assert "execution.order.submitted" in received


@pytest.mark.asyncio
async def test_adapter_cancel_order(adapter, mock_client, bus):
    received = []

    async def handler(ch, ev):
        received.append(ch)

    await bus.subscribe("execution.order.cancelled", handler)
    await adapter.cancel_order("order-abc")
    mock_client.cancel_order.assert_awaited_once_with("order-abc")
    assert "execution.order.cancelled" in received


@pytest.mark.asyncio
async def test_adapter_get_positions(adapter):
    from trading_platform.core.models import Position

    adapter._positions = [Position(symbol="AAPL", quantity=100)]
    positions = await adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_adapter_get_account(adapter):
    adapter._account_info = {"equity": 100000}
    account = await adapter.get_account()
    assert account["equity"] == 100000


@pytest.mark.asyncio
async def test_adapter_sync_portfolio(adapter, mock_client, bus):
    mock_portfolio = SimpleNamespace(
        positions=[
            SimpleNamespace(
                symbol="AAPL",
                quantity=100,
                average_price=150.0,
                market_value=15500.0,
                unrealized_pnl=500.0,
            ),
        ],
        buying_power=SimpleNamespace(cash=50000, margin=100000),
        equity=115500,
    )
    mock_client.get_portfolio.return_value = mock_portfolio

    received = []

    async def handler(ch, ev):
        received.append(ch)

    await bus.subscribe("execution.portfolio.update", handler)
    await adapter.sync_portfolio()
    assert len(adapter._positions) == 1
    assert adapter._account_info["equity"] == 115500
    assert "execution.portfolio.update" in received
