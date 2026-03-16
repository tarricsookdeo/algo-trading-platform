"""Tests for the options execution adapter."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_platform.adapters.options.adapter import OptionsExecAdapter
from trading_platform.adapters.options.config import OptionsConfig
from trading_platform.core.enums import AssetClass, ContractType, OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import MultiLegOrder, Order, Position


# ── Config ──────────────────────────────────────────────────────────


class TestOptionsConfig:
    def test_defaults(self):
        cfg = OptionsConfig()
        assert cfg.api_secret == ""
        assert cfg.account_id == ""
        assert cfg.poll_interval == 2.0
        assert cfg.portfolio_refresh == 30.0
        assert cfg.token_validity_minutes == 15

    def test_custom_values(self):
        cfg = OptionsConfig(
            api_secret="secret",
            account_id="acc-123",
            poll_interval=1.0,
            portfolio_refresh=60.0,
            token_validity_minutes=30,
        )
        assert cfg.api_secret == "secret"
        assert cfg.account_id == "acc-123"
        assert cfg.portfolio_refresh == 60.0
        assert cfg.token_validity_minutes == 30


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def config():
    return OptionsConfig(api_secret="test-secret", account_id="test-acc")


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.place_option_order = AsyncMock()
    client.place_multileg_order = AsyncMock()
    client.cancel_order = AsyncMock()
    client.get_option_portfolio = AsyncMock()
    client.perform_preflight = AsyncMock()
    client.perform_multileg_preflight = AsyncMock()
    client.get_option_chain = AsyncMock(return_value={"chain": []})
    client.get_option_expirations = AsyncMock(return_value=["2024-01-19", "2024-02-16"])
    return client


@pytest.fixture
def adapter(config, bus, mock_client):
    a = OptionsExecAdapter(config, bus)
    a._client = mock_client
    return a


def _option_order(**kwargs) -> Order:
    defaults = dict(
        symbol="AAPL240119C00150000",
        option_symbol="AAPL240119C00150000",
        asset_class=AssetClass.OPTION,
        contract_type=ContractType.CALL,
        strike_price=Decimal("150"),
        expiration_date="2024-01-19",
        underlying_symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    defaults.update(kwargs)
    return Order(**defaults)


def _option_leg(**kwargs) -> Order:
    """Helper to build a valid OPTION leg for a MultiLegOrder."""
    return _option_order(**kwargs)


# ── Connect / Disconnect ─────────────────────────────────────────────


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_calls_client_and_marks_connected(self, adapter, mock_client):
        await adapter.connect()
        mock_client.connect.assert_awaited_once()
        assert adapter._connected is True
        # Clean up background task
        if adapter._portfolio_task:
            adapter._portfolio_task.cancel()
            try:
                await adapter._portfolio_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_connect_starts_portfolio_task(self, adapter):
        await adapter.connect()
        assert adapter._portfolio_task is not None
        assert not adapter._portfolio_task.done()
        adapter._portfolio_task.cancel()
        try:
            await adapter._portfolio_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_connect_publishes_connected_event(self, adapter, bus):
        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.account.update", capture)
        await adapter.connect()

        assert any(e.get("status") == "connected" for e in events)
        assert any(e.get("asset_class") == "option" for e in events)

        if adapter._portfolio_task:
            adapter._portfolio_task.cancel()
            try:
                await adapter._portfolio_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_disconnect_cancels_task_and_calls_client(self, adapter, mock_client):
        await adapter.connect()
        await adapter.disconnect()
        mock_client.disconnect.assert_awaited_once()
        assert adapter._connected is False


# ── submit_option_order / submit_order ───────────────────────────────


class TestSubmitOptionOrder:
    @pytest.mark.asyncio
    async def test_market_buy_call(self, adapter, mock_client, bus):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        order = _option_order(side=OrderSide.BUY, order_type=OrderType.MARKET)
        result = await adapter.submit_order(order)

        mock_client.place_option_order.assert_awaited_once()
        assert result is mock_order
        # Let background task settle
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_limit_sell_put(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        order = _option_order(
            contract_type=ContractType.PUT,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            limit_price=5.50,
        )
        await adapter.submit_option_order(order)

        call_kwargs = mock_client.place_option_order.call_args[0][0]
        assert call_kwargs.limit_price == Decimal("5.5")
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_stop_order_includes_stop_price(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        order = _option_order(
            order_type=OrderType.STOP,
            stop_price=3.00,
        )
        await adapter.submit_option_order(order)

        call_kwargs = mock_client.place_option_order.call_args[0][0]
        assert call_kwargs.stop_price == Decimal("3.0")
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_submit_publishes_order_submitted_event(self, adapter, mock_client, bus):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.order.submitted", capture)
        order = _option_order()
        await adapter.submit_option_order(order)

        assert len(events) == 1
        assert events[0]["asset_class"] == "option"
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_option_symbol_used_when_set(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        order = _option_order(
            symbol="AAPL",
            option_symbol="AAPL240119C00150000",
        )
        await adapter.submit_option_order(order)

        call_kwargs = mock_client.place_option_order.call_args[0][0]
        # The instrument symbol should be the option_symbol, not the generic symbol
        assert call_kwargs.instrument.symbol == "AAPL240119C00150000"
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_rate_limit_error_publishes_event(self, adapter, mock_client, bus):
        from public_api_sdk.exceptions import RateLimitError

        mock_client.place_option_order.side_effect = RateLimitError("rate limited")

        errors = []

        async def capture(ch, ev):
            errors.append(ev)

        await bus.subscribe("execution.order.error", capture)

        order = _option_order()
        with pytest.raises(RateLimitError):
            await adapter.submit_option_order(order)

        assert len(errors) == 1
        assert errors[0]["error"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_api_error_publishes_event(self, adapter, mock_client, bus):
        from public_api_sdk.exceptions import APIError

        mock_client.place_option_order.side_effect = APIError("api error")

        errors = []

        async def capture(ch, ev):
            errors.append(ev)

        await bus.subscribe("execution.order.error", capture)

        order = _option_order()
        with pytest.raises(APIError):
            await adapter.submit_option_order(order)

        assert len(errors) == 1
        assert errors[0]["error"] == "api_error"


# ── submit_multileg_order ─────────────────────────────────────────────


class TestSubmitMultilegOrder:
    def _two_leg_order(self) -> MultiLegOrder:
        buy_leg = _option_leg(side=OrderSide.BUY, quantity=Decimal("1"))
        sell_leg = _option_leg(
            side=OrderSide.SELL,
            strike_price=Decimal("155"),
            quantity=Decimal("1"),
        )
        return MultiLegOrder(
            legs=[buy_leg, sell_leg],
            strategy_type="vertical_spread",
            net_debit_or_credit=Decimal("2.50"),
        )

    @pytest.mark.asyncio
    async def test_two_leg_spread_submits(self, adapter, mock_client, bus):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_multileg_order.return_value = mock_order

        multileg = self._two_leg_order()
        result = await adapter.submit_multileg_order(multileg)

        mock_client.place_multileg_order.assert_awaited_once()
        assert result is mock_order
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_multileg_publishes_submitted_event(self, adapter, mock_client, bus):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_multileg_order.return_value = mock_order

        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.order.submitted", capture)
        await adapter.submit_multileg_order(self._two_leg_order())

        assert len(events) == 1
        assert events[0]["type"] == "multileg"
        assert events[0]["legs"] == 2
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_invalid_uuid_id_gets_replaced(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_multileg_order.return_value = mock_order

        multileg = self._two_leg_order()
        multileg.id = "not-a-uuid"
        await adapter.submit_multileg_order(multileg)

        call_args = mock_client.place_multileg_order.call_args[0][0]
        import uuid
        # Should have been replaced with a valid UUID
        uuid.UUID(call_args.order_id)  # raises ValueError if invalid
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_api_error_publishes_event(self, adapter, mock_client, bus):
        from public_api_sdk.exceptions import APIError

        mock_client.place_multileg_order.side_effect = APIError("api error")

        errors = []

        async def capture(ch, ev):
            errors.append(ev)

        await bus.subscribe("execution.order.error", capture)

        with pytest.raises(APIError):
            await adapter.submit_multileg_order(self._two_leg_order())

        assert len(errors) == 1
        assert errors[0]["error"] == "api_error"

    @pytest.mark.asyncio
    async def test_four_leg_condor_leg_count(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_multileg_order.return_value = mock_order

        legs = [
            _option_leg(side=OrderSide.BUY, strike_price=Decimal(str(s)), quantity=Decimal("1"))
            for s in [140, 145, 155, 160]
        ]
        multileg = MultiLegOrder(
            legs=legs,
            strategy_type="iron_condor",
            net_debit_or_credit=Decimal("1.00"),
        )
        await adapter.submit_multileg_order(multileg)

        call_args = mock_client.place_multileg_order.call_args[0][0]
        assert len(call_args.legs) == 4
        await asyncio.sleep(0)


# ── cancel_option_order ──────────────────────────────────────────────


class TestCancelOptionOrder:
    @pytest.mark.asyncio
    async def test_cancel_success_publishes_event(self, adapter, mock_client, bus):
        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.order.cancelled", capture)
        await adapter.cancel_option_order("order-123")

        mock_client.cancel_order.assert_awaited_once_with("order-123")
        assert len(events) == 1
        assert events[0]["order_id"] == "order-123"

    @pytest.mark.asyncio
    async def test_cancel_order_delegates_to_cancel_option_order(self, adapter, mock_client):
        await adapter.cancel_order("order-abc")
        mock_client.cancel_order.assert_awaited_once_with("order-abc")

    @pytest.mark.asyncio
    async def test_cancel_api_error_publishes_event(self, adapter, mock_client, bus):
        from public_api_sdk.exceptions import APIError

        mock_client.cancel_order.side_effect = APIError("cancel failed")

        errors = []

        async def capture(ch, ev):
            errors.append(ev)

        await bus.subscribe("execution.order.error", capture)

        with pytest.raises(APIError):
            await adapter.cancel_option_order("order-bad")

        assert len(errors) == 1
        assert errors[0]["error"] == "cancel_failed"


# ── get_positions / get_option_positions / get_account ───────────────


class TestPositionsAndAccount:
    @pytest.mark.asyncio
    async def test_get_positions_returns_cached_copy(self, adapter):
        adapter._positions = [Position(symbol="AAPL-OPT", quantity=Decimal("5"))]
        positions = await adapter.get_positions()
        assert len(positions) == 1
        assert positions is not adapter._positions  # defensive copy

    @pytest.mark.asyncio
    async def test_get_option_positions_returns_cached_copy(self, adapter):
        adapter._positions = [Position(symbol="AAPL-OPT", quantity=Decimal("5"))]
        positions = await adapter.get_option_positions()
        assert len(positions) == 1
        assert positions is not adapter._positions

    @pytest.mark.asyncio
    async def test_get_account_returns_cached_copy(self, adapter):
        adapter._account_info = {"option_buying_power": 10_000}
        account = await adapter.get_account()
        assert account == {"option_buying_power": 10_000}
        assert account is not adapter._account_info


# ── preflight_option_order ───────────────────────────────────────────


class TestPreflightOptionOrder:
    @pytest.mark.asyncio
    async def test_preflight_calls_client(self, adapter, mock_client):
        mock_client.perform_preflight.return_value = {"buying_power_effect": -500.0}

        order = _option_order(order_type=OrderType.LIMIT, limit_price=5.00)
        result = await adapter.preflight_option_order(order)

        mock_client.perform_preflight.assert_awaited_once()
        assert result == {"buying_power_effect": -500.0}

    @pytest.mark.asyncio
    async def test_preflight_uses_option_symbol(self, adapter, mock_client):
        mock_client.perform_preflight.return_value = {}
        order = _option_order(
            symbol="AAPL",
            option_symbol="AAPL240119C00150000",
        )
        await adapter.preflight_option_order(order)

        call_args = mock_client.perform_preflight.call_args[0][0]
        assert call_args.instrument.symbol == "AAPL240119C00150000"

    @pytest.mark.asyncio
    async def test_preflight_no_limit_price(self, adapter, mock_client):
        mock_client.perform_preflight.return_value = {}
        order = _option_order(order_type=OrderType.MARKET, limit_price=None)
        await adapter.preflight_option_order(order)

        call_args = mock_client.perform_preflight.call_args[0][0]
        assert call_args.limit_price is None


# ── get_option_chain / get_option_expirations ─────────────────────────


class TestChainAndExpirations:
    @pytest.mark.asyncio
    async def test_get_option_chain_delegates(self, adapter, mock_client):
        mock_client.get_option_chain.return_value = {"calls": [], "puts": []}
        result = await adapter.get_option_chain("AAPL")
        mock_client.get_option_chain.assert_awaited_once_with("AAPL")
        assert result == {"calls": [], "puts": []}

    @pytest.mark.asyncio
    async def test_get_option_expirations_delegates(self, adapter, mock_client):
        mock_client.get_option_expirations.return_value = ["2024-01-19", "2024-02-16"]
        result = await adapter.get_option_expirations("AAPL")
        mock_client.get_option_expirations.assert_awaited_once_with("AAPL")
        assert result == ["2024-01-19", "2024-02-16"]


# ── sync_portfolio ────────────────────────────────────────────────────


class TestSyncPortfolio:
    def _mock_option_position(self, symbol="AAPL240119C00150000", quantity="5"):
        pos = MagicMock()
        pos.symbol = symbol
        pos.quantity = quantity
        pos.average_price = "10.0"
        pos.market_value = "500.0"
        pos.unrealized_pnl = "50.0"
        pos.instrument_type = "OPTION"
        return pos

    @pytest.mark.asyncio
    async def test_sync_updates_positions(self, adapter, mock_client, bus):
        mock_portfolio = MagicMock()
        mock_portfolio.positions = [self._mock_option_position()]
        mock_client.get_option_portfolio.return_value = mock_portfolio

        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.portfolio.update", capture)
        await adapter.sync_portfolio()

        assert len(adapter._positions) == 1
        assert adapter._positions[0].symbol == "AAPL240119C00150000"
        assert adapter._positions[0].quantity == Decimal("5")
        assert len(events) == 1
        assert events[0]["asset_class"] == "option"

    @pytest.mark.asyncio
    async def test_sync_filters_non_option_positions(self, adapter, mock_client):
        equity_pos = self._mock_option_position()
        equity_pos.instrument_type = "EQUITY"
        option_pos = self._mock_option_position(symbol="TSLA240119C00200000", quantity="2")

        mock_portfolio = MagicMock()
        mock_portfolio.positions = [equity_pos, option_pos]
        mock_client.get_option_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()

        # Only the OPTION position should be included
        assert len(adapter._positions) == 1
        assert adapter._positions[0].symbol == "TSLA240119C00200000"

    @pytest.mark.asyncio
    async def test_sync_empty_portfolio(self, adapter, mock_client):
        mock_portfolio = MagicMock()
        mock_portfolio.positions = []
        mock_client.get_option_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()
        assert adapter._positions == []

    @pytest.mark.asyncio
    async def test_sync_no_positions_attribute(self, adapter, mock_client):
        mock_portfolio = MagicMock(spec=[])  # no attributes
        mock_client.get_option_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()
        assert adapter._positions == []

    @pytest.mark.asyncio
    async def test_sync_error_is_swallowed(self, adapter, mock_client):
        mock_client.get_option_portfolio.side_effect = RuntimeError("network error")
        # Should not raise
        await adapter.sync_portfolio()


# ── _track_order ──────────────────────────────────────────────────────


class TestTrackOrder:
    async def _run_track_with_status(self, adapter, bus, status_name: str) -> list:
        events = []

        async def capture(ch, ev):
            events.append((ch, ev))

        for channel in [
            "execution.order.filled",
            "execution.order.partially_filled",
            "execution.order.cancelled",
            "execution.order.rejected",
        ]:
            await bus.subscribe(channel, capture)

        mock_async_order = AsyncMock()

        async def fake_subscribe(callback):
            update = MagicMock()
            update.status.name = status_name
            await callback(update)

        mock_async_order.subscribe_updates = fake_subscribe
        mock_async_order.wait_for_terminal_status = AsyncMock()

        await adapter._track_order("order-track-1", mock_async_order)
        return events

    @pytest.mark.asyncio
    async def test_filled_publishes_event(self, adapter, bus):
        events = await self._run_track_with_status(adapter, bus, "FILLED")
        channels = [ch for ch, _ in events]
        assert "execution.order.filled" in channels

    @pytest.mark.asyncio
    async def test_cancelled_publishes_event(self, adapter, bus):
        events = await self._run_track_with_status(adapter, bus, "CANCELLED")
        channels = [ch for ch, _ in events]
        assert "execution.order.cancelled" in channels

    @pytest.mark.asyncio
    async def test_rejected_publishes_event(self, adapter, bus):
        events = await self._run_track_with_status(adapter, bus, "REJECTED")
        channels = [ch for ch, _ in events]
        assert "execution.order.rejected" in channels

    @pytest.mark.asyncio
    async def test_partially_filled_publishes_event(self, adapter, bus):
        events = await self._run_track_with_status(adapter, bus, "PARTIALLY_FILLED")
        channels = [ch for ch, _ in events]
        assert "execution.order.partially_filled" in channels

    @pytest.mark.asyncio
    async def test_exception_during_tracking_does_not_raise(self, adapter, bus):
        mock_async_order = AsyncMock()
        mock_async_order.subscribe_updates = AsyncMock(side_effect=RuntimeError("connection lost"))
        mock_async_order.wait_for_terminal_status = AsyncMock()

        # Should not raise
        await adapter._track_order("order-err", mock_async_order)

    @pytest.mark.asyncio
    async def test_track_cleans_up_tracked_orders(self, adapter, bus):
        mock_async_order = AsyncMock()
        mock_async_order.subscribe_updates = AsyncMock()
        mock_async_order.wait_for_terminal_status = AsyncMock()

        adapter._tracked_orders["order-cleanup"] = mock_async_order
        await adapter._track_order("order-cleanup", mock_async_order)
        assert "order-cleanup" not in adapter._tracked_orders
