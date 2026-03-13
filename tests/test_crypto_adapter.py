"""Tests for the crypto execution adapter."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_platform.adapters.crypto.adapter import CryptoExecAdapter
from trading_platform.adapters.crypto.config import CryptoConfig
from trading_platform.core.enums import AssetClass, OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Order, Position


# ── Config Tests ─────────────────────────────────────────────────────


class TestCryptoConfig:
    def test_defaults(self):
        cfg = CryptoConfig()
        assert cfg.api_secret == ""
        assert cfg.account_id == ""
        assert cfg.trading_pairs == ["BTC-USD", "ETH-USD"]
        assert cfg.poll_interval == 2.0
        assert cfg.portfolio_refresh == 30.0
        assert cfg.token_validity_minutes == 15

    def test_custom_values(self):
        cfg = CryptoConfig(
            api_secret="secret",
            account_id="acc123",
            trading_pairs=["SOL-USD"],
            poll_interval=1.0,
            portfolio_refresh=60.0,
            token_validity_minutes=30,
        )
        assert cfg.api_secret == "secret"
        assert cfg.account_id == "acc123"
        assert cfg.trading_pairs == ["SOL-USD"]
        assert cfg.portfolio_refresh == 60.0


# ── Adapter Tests ────────────────────────────────────────────────────


@pytest.fixture
def config():
    return CryptoConfig(api_secret="test-secret", account_id="test-acc")


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.place_crypto_order = AsyncMock()
    client.cancel_crypto_order = AsyncMock()
    client.get_crypto_portfolio = AsyncMock()
    return client


@pytest.fixture
def adapter(config, bus, mock_client):
    a = CryptoExecAdapter(config, bus)
    a._client = mock_client
    return a


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect(self, adapter, mock_client):
        await adapter.connect()
        mock_client.connect.assert_awaited_once()
        assert adapter._connected is True
        assert adapter._portfolio_task is not None
        # Clean up the background task
        adapter._portfolio_task.cancel()
        try:
            await adapter._portfolio_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter, mock_client):
        await adapter.connect()
        await adapter.disconnect()
        mock_client.disconnect.assert_awaited_once()
        assert adapter._connected is False


class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_market_buy(self, adapter, bus, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_crypto_order.return_value = mock_order

        events = []
        async def capture(ch, ev):
            events.append(ev)
        await bus.subscribe("execution.order.submitted", capture)

        order = Order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.5"),
            asset_class=AssetClass.CRYPTO,
        )
        result = await adapter.submit_order(order)

        mock_client.place_crypto_order.assert_awaited_once()
        call_kwargs = mock_client.place_crypto_order.call_args[1]
        assert call_kwargs["symbol"] == "BTC-USD"
        assert call_kwargs["side"] == "buy"
        assert call_kwargs["order_type"] == "market"
        assert call_kwargs["quantity"] == Decimal("0.5")
        assert order.order_id != ""
        assert order.status == "new"
        assert len(events) == 1
        assert events[0]["asset_class"] == "crypto"
        # Allow tracking task to be collected
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_limit_sell(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_crypto_order.return_value = mock_order

        order = Order(
            symbol="ETH-USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("2.0"),
            limit_price=3500.0,
            asset_class=AssetClass.CRYPTO,
        )
        await adapter.submit_order(order)

        call_kwargs = mock_client.place_crypto_order.call_args[1]
        assert call_kwargs["side"] == "sell"
        assert call_kwargs["order_type"] == "limit"
        assert call_kwargs["limit_price"] == Decimal("3500.0")
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_stop_order(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_crypto_order.return_value = mock_order

        order = Order(
            symbol="BTC-USD",
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=Decimal("1.0"),
            stop_price=40000.0,
            asset_class=AssetClass.CRYPTO,
        )
        await adapter.submit_order(order)

        call_kwargs = mock_client.place_crypto_order.call_args[1]
        assert call_kwargs["stop_price"] == Decimal("40000.0")
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_submit_failure_publishes_error(self, adapter, bus, mock_client):
        mock_client.place_crypto_order.side_effect = RuntimeError("API down")

        errors = []
        async def capture(ch, ev):
            errors.append(ev)
        await bus.subscribe("execution.order.error", capture)

        order = Order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        with pytest.raises(RuntimeError, match="API down"):
            await adapter.submit_order(order)

        assert len(errors) == 1
        assert errors[0]["error"] == "api_error"


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_success(self, adapter, bus, mock_client):
        events = []
        async def capture(ch, ev):
            events.append(ev)
        await bus.subscribe("execution.order.cancelled", capture)

        await adapter.cancel_order("order-123")
        mock_client.cancel_crypto_order.assert_awaited_once_with("order-123")
        assert len(events) == 1
        assert events[0]["order_id"] == "order-123"

    @pytest.mark.asyncio
    async def test_cancel_failure(self, adapter, bus, mock_client):
        mock_client.cancel_crypto_order.side_effect = RuntimeError("not found")

        errors = []
        async def capture(ch, ev):
            errors.append(ev)
        await bus.subscribe("execution.order.error", capture)

        with pytest.raises(RuntimeError, match="not found"):
            await adapter.cancel_order("bad-id")

        assert len(errors) == 1
        assert errors[0]["error"] == "cancel_failed"


class TestPositionsAndAccount:
    @pytest.mark.asyncio
    async def test_get_positions_returns_cached(self, adapter):
        adapter._positions = [
            Position(symbol="BTC-USD", quantity=Decimal("1.5")),
            Position(symbol="ETH-USD", quantity=Decimal("10")),
        ]
        positions = await adapter.get_positions()
        assert len(positions) == 2
        assert positions[0].symbol == "BTC-USD"
        # Returns a copy
        assert positions is not adapter._positions

    @pytest.mark.asyncio
    async def test_get_account_returns_cached(self, adapter):
        adapter._account_info = {"balance": 50_000}
        account = await adapter.get_account()
        assert account == {"balance": 50_000}
        assert account is not adapter._account_info


class TestSyncPortfolio:
    @pytest.mark.asyncio
    async def test_sync_updates_positions(self, adapter, bus, mock_client):
        mock_pos = MagicMock()
        mock_pos.symbol = "BTC-USD"
        mock_pos.quantity = "0.75"
        mock_pos.average_price = "42000.0"
        mock_pos.market_value = "31500.0"
        mock_pos.unrealized_pnl = "500.0"

        mock_portfolio = MagicMock()
        mock_portfolio.positions = [mock_pos]
        mock_client.get_crypto_portfolio.return_value = mock_portfolio

        events = []
        async def capture(ch, ev):
            events.append(ev)
        await bus.subscribe("execution.portfolio.update", capture)

        await adapter.sync_portfolio()

        assert len(adapter._positions) == 1
        assert adapter._positions[0].symbol == "BTC-USD"
        assert adapter._positions[0].quantity == Decimal("0.75")
        assert len(events) == 1
        assert events[0]["asset_class"] == "crypto"

    @pytest.mark.asyncio
    async def test_sync_empty_portfolio(self, adapter, mock_client):
        mock_portfolio = MagicMock()
        mock_portfolio.positions = []
        mock_client.get_crypto_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()
        assert adapter._positions == []

    @pytest.mark.asyncio
    async def test_sync_no_positions_attr(self, adapter, mock_client):
        mock_portfolio = MagicMock(spec=[])  # no attributes
        mock_client.get_crypto_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()
        assert adapter._positions == []

    @pytest.mark.asyncio
    async def test_sync_error_handled(self, adapter, mock_client):
        mock_client.get_crypto_portfolio.side_effect = RuntimeError("network error")
        # Should not raise
        await adapter.sync_portfolio()
