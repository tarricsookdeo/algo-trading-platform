"""Tests for options order model, adapter, and routing."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_platform.adapters.options.adapter import OptionsExecAdapter
from trading_platform.adapters.options.config import OptionsConfig
from trading_platform.core.enums import (
    AssetClass,
    ContractType,
    OrderSide,
    OrderStatus,
    OrderType,
)
from trading_platform.core.events import EventBus
from trading_platform.core.models import MultiLegOrder, Order, Position
from trading_platform.core.order_router import OrderRouter


# ── Helpers ───────────────────────────────────────────────────────────


def _make_option_order(**overrides) -> Order:
    """Build a valid OPTION Order with sensible defaults."""
    defaults = {
        "symbol": "AAPL250321C00200000",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("1"),
        "limit_price": 5.50,
        "asset_class": AssetClass.OPTION,
        "contract_type": ContractType.CALL,
        "strike_price": Decimal("200"),
        "expiration_date": date(2025, 3, 21),
        "underlying_symbol": "AAPL",
        "option_symbol": "AAPL250321C00200000",
    }
    defaults.update(overrides)
    return Order(**defaults)


# ══════════════════════════════════════════════════════════════════════
# 1. Options Order Model Validation
# ══════════════════════════════════════════════════════════════════════


class TestOptionOrderValidation:
    """Options-specific fields required when asset_class=OPTION."""

    def test_valid_option_order(self):
        o = _make_option_order()
        assert o.asset_class == AssetClass.OPTION
        assert o.contract_type == ContractType.CALL
        assert o.strike_price == Decimal("200")
        assert o.expiration_date == date(2025, 3, 21)
        assert o.underlying_symbol == "AAPL"

    def test_put_option(self):
        o = _make_option_order(contract_type=ContractType.PUT)
        assert o.contract_type == ContractType.PUT

    def test_missing_contract_type_raises(self):
        with pytest.raises(ValueError, match="contract_type"):
            _make_option_order(contract_type=None)

    def test_missing_strike_price_raises(self):
        with pytest.raises(ValueError, match="strike_price"):
            _make_option_order(strike_price=None)

    def test_missing_expiration_date_raises(self):
        with pytest.raises(ValueError, match="expiration_date"):
            _make_option_order(expiration_date=None)

    def test_missing_underlying_symbol_raises(self):
        with pytest.raises(ValueError, match="underlying_symbol"):
            _make_option_order(underlying_symbol="")

    def test_multiple_missing_fields(self):
        with pytest.raises(ValueError, match="contract_type.*strike_price"):
            _make_option_order(contract_type=None, strike_price=None)

    def test_equity_order_ignores_option_fields(self):
        o = Order(
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            quantity=Decimal("10"),
        )
        assert o.contract_type is None
        assert o.strike_price is None
        assert o.expiration_date is None

    def test_crypto_order_ignores_option_fields(self):
        o = Order(
            symbol="BTC-USD",
            asset_class=AssetClass.CRYPTO,
            quantity=Decimal("0.5"),
        )
        assert o.contract_type is None


# ══════════════════════════════════════════════════════════════════════
# 2. MultiLegOrder Model
# ══════════════════════════════════════════════════════════════════════


class TestMultiLegOrder:
    def test_valid_multileg(self):
        legs = [
            _make_option_order(side=OrderSide.BUY, strike_price=Decimal("200")),
            _make_option_order(side=OrderSide.SELL, strike_price=Decimal("210")),
        ]
        ml = MultiLegOrder(
            id="ml-1",
            legs=legs,
            strategy_type="vertical_spread",
            net_debit_or_credit=Decimal("-2.50"),
        )
        assert len(ml.legs) == 2
        assert ml.strategy_type == "vertical_spread"
        assert ml.net_debit_or_credit == Decimal("-2.50")
        assert ml.status == OrderStatus.NEW

    def test_empty_legs_raises(self):
        with pytest.raises(ValueError, match="at least one leg"):
            MultiLegOrder(id="ml-2", legs=[])

    def test_non_option_leg_raises(self):
        equity_leg = Order(
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            quantity=Decimal("10"),
        )
        with pytest.raises(ValueError, match="asset_class OPTION"):
            MultiLegOrder(id="ml-3", legs=[equity_leg])

    def test_default_status_is_new(self):
        leg = _make_option_order()
        ml = MultiLegOrder(legs=[leg])
        assert ml.status == OrderStatus.NEW

    def test_timestamps_optional(self):
        leg = _make_option_order()
        ml = MultiLegOrder(legs=[leg])
        assert ml.created_at is None
        assert ml.updated_at is None


# ══════════════════════════════════════════════════════════════════════
# 3. Options Config
# ══════════════════════════════════════════════════════════════════════


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
            account_id="acc123",
            poll_interval=1.0,
            portfolio_refresh=60.0,
            token_validity_minutes=30,
        )
        assert cfg.api_secret == "secret"
        assert cfg.account_id == "acc123"
        assert cfg.portfolio_refresh == 60.0


# ══════════════════════════════════════════════════════════════════════
# 4. Options Adapter
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def options_config():
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
    client.get_option_chain = AsyncMock()
    client.get_option_expirations = AsyncMock()
    return client


@pytest.fixture
def adapter(options_config, bus, mock_client):
    a = OptionsExecAdapter(options_config, bus)
    a._client = mock_client
    return a


class TestOptionsAdapterConnect:
    @pytest.mark.asyncio
    async def test_connect(self, adapter, mock_client):
        await adapter.connect()
        mock_client.connect.assert_awaited_once()
        assert adapter._connected is True
        assert adapter._portfolio_task is not None
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


class TestSubmitOptionOrder:
    @pytest.mark.asyncio
    async def test_submit_single_leg(self, adapter, bus, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.order.submitted", capture)

        order = _make_option_order()
        result = await adapter.submit_option_order(order)

        mock_client.place_option_order.assert_awaited_once()
        assert order.order_id != ""
        assert order.status == "new"
        assert len(events) == 1
        assert events[0]["asset_class"] == "option"
        assert events[0]["contract_type"] == "call"
        assert events[0]["strike_price"] == "200"
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_submit_order_delegates(self, adapter, mock_client):
        """submit_order() should delegate to submit_option_order()."""
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        order = _make_option_order()
        await adapter.submit_order(order)
        mock_client.place_option_order.assert_awaited_once()
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_submit_with_stop_price(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_option_order.return_value = mock_order

        order = _make_option_order(
            order_type=OrderType.STOP,
            stop_price=4.00,
            limit_price=None,
        )
        await adapter.submit_option_order(order)
        mock_client.place_option_order.assert_awaited_once()
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_submit_failure_publishes_error(self, adapter, bus, mock_client):
        from public_api_sdk.exceptions import APIError

        mock_client.place_option_order.side_effect = APIError("API down")

        errors = []

        async def capture(ch, ev):
            errors.append(ev)

        await bus.subscribe("execution.order.error", capture)

        order = _make_option_order()
        with pytest.raises(APIError):
            await adapter.submit_option_order(order)

        assert len(errors) == 1
        assert errors[0]["error"] == "api_error"


class TestSubmitMultilegOrder:
    @pytest.mark.asyncio
    async def test_market_multileg(self, adapter, bus, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_multileg_order.return_value = mock_order

        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.order.submitted", capture)

        legs = [
            _make_option_order(side=OrderSide.BUY),
            _make_option_order(side=OrderSide.SELL, strike_price=Decimal("210")),
        ]
        ml = MultiLegOrder(
            legs=legs,
            strategy_type="vertical_spread",
        )
        result = await adapter.submit_multileg_order(ml)

        mock_client.place_multileg_order.assert_awaited_once()
        assert len(events) == 1
        assert events[0]["type"] == "multileg"
        assert events[0]["strategy_type"] == "vertical_spread"
        assert events[0]["legs"] == 2
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_limit_multileg(self, adapter, mock_client):
        mock_order = AsyncMock()
        mock_order.subscribe_updates = AsyncMock()
        mock_order.wait_for_terminal_status = AsyncMock()
        mock_client.place_multileg_order.return_value = mock_order

        legs = [
            _make_option_order(side=OrderSide.BUY),
            _make_option_order(side=OrderSide.SELL, strike_price=Decimal("210")),
        ]
        ml = MultiLegOrder(
            legs=legs,
            strategy_type="iron_condor",
            net_debit_or_credit=Decimal("-3.00"),
        )
        await adapter.submit_multileg_order(ml)
        mock_client.place_multileg_order.assert_awaited_once()
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_multileg_failure(self, adapter, bus, mock_client):
        from public_api_sdk.exceptions import APIError

        mock_client.place_multileg_order.side_effect = APIError("bad request")

        errors = []

        async def capture(ch, ev):
            errors.append(ev)

        await bus.subscribe("execution.order.error", capture)

        legs = [
            _make_option_order(side=OrderSide.BUY),
            _make_option_order(side=OrderSide.SELL, strike_price=Decimal("210")),
        ]
        ml = MultiLegOrder(legs=legs, strategy_type="spread")
        with pytest.raises(APIError):
            await adapter.submit_multileg_order(ml)

        assert len(errors) == 1
        assert errors[0]["error"] == "api_error"


class TestCancelOptionOrder:
    @pytest.mark.asyncio
    async def test_cancel_success(self, adapter, bus, mock_client):
        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.order.cancelled", capture)

        await adapter.cancel_option_order("opt-123")
        mock_client.cancel_order.assert_awaited_once_with("opt-123")
        assert len(events) == 1
        assert events[0]["order_id"] == "opt-123"

    @pytest.mark.asyncio
    async def test_cancel_delegates(self, adapter, mock_client):
        """cancel_order() should delegate to cancel_option_order()."""
        await adapter.cancel_order("opt-456")
        mock_client.cancel_order.assert_awaited_once_with("opt-456")

    @pytest.mark.asyncio
    async def test_cancel_failure(self, adapter, bus, mock_client):
        from public_api_sdk.exceptions import APIError

        mock_client.cancel_order.side_effect = APIError("not found")

        errors = []

        async def capture(ch, ev):
            errors.append(ev)

        await bus.subscribe("execution.order.error", capture)

        with pytest.raises(APIError):
            await adapter.cancel_option_order("bad-id")

        assert len(errors) == 1
        assert errors[0]["error"] == "cancel_failed"


class TestOptionPositions:
    @pytest.mark.asyncio
    async def test_get_positions_returns_cached(self, adapter):
        adapter._positions = [
            Position(symbol="AAPL250321C00200000", quantity=Decimal("5")),
            Position(symbol="AAPL250321P00180000", quantity=Decimal("3")),
        ]
        positions = await adapter.get_positions()
        assert len(positions) == 2
        assert positions[0].symbol == "AAPL250321C00200000"
        assert positions is not adapter._positions

    @pytest.mark.asyncio
    async def test_get_option_positions(self, adapter):
        adapter._positions = [
            Position(symbol="SPY250418C00500000", quantity=Decimal("10")),
        ]
        positions = await adapter.get_option_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "SPY250418C00500000"

    @pytest.mark.asyncio
    async def test_get_account_returns_cached(self, adapter):
        adapter._account_info = {"balance": 25_000}
        account = await adapter.get_account()
        assert account == {"balance": 25_000}
        assert account is not adapter._account_info


class TestPreflightAndChain:
    @pytest.mark.asyncio
    async def test_preflight(self, adapter, mock_client):
        mock_client.perform_preflight.return_value = {"status": "ok"}
        order = _make_option_order()
        result = await adapter.preflight_option_order(order)
        mock_client.perform_preflight.assert_awaited_once()
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_option_chain(self, adapter, mock_client):
        mock_client.get_option_chain.return_value = {"chain": []}
        result = await adapter.get_option_chain("AAPL")
        mock_client.get_option_chain.assert_awaited_once_with("AAPL")
        assert result == {"chain": []}

    @pytest.mark.asyncio
    async def test_get_option_expirations(self, adapter, mock_client):
        mock_client.get_option_expirations.return_value = ["2025-03-21", "2025-04-18"]
        result = await adapter.get_option_expirations("AAPL")
        mock_client.get_option_expirations.assert_awaited_once_with("AAPL")
        assert result == ["2025-03-21", "2025-04-18"]


class TestOptionsSyncPortfolio:
    @pytest.mark.asyncio
    async def test_sync_updates_positions(self, adapter, bus, mock_client):
        mock_pos = MagicMock()
        mock_pos.symbol = "AAPL250321C00200000"
        mock_pos.quantity = "5"
        mock_pos.average_price = "3.50"
        mock_pos.market_value = "1750.0"
        mock_pos.unrealized_pnl = "250.0"
        mock_pos.instrument_type = "OPTION"

        mock_portfolio = MagicMock()
        mock_portfolio.positions = [mock_pos]
        mock_client.get_option_portfolio.return_value = mock_portfolio

        events = []

        async def capture(ch, ev):
            events.append(ev)

        await bus.subscribe("execution.portfolio.update", capture)

        await adapter.sync_portfolio()
        assert len(adapter._positions) == 1
        assert adapter._positions[0].symbol == "AAPL250321C00200000"
        assert adapter._positions[0].quantity == Decimal("5")
        assert len(events) == 1
        assert events[0]["asset_class"] == "option"

    @pytest.mark.asyncio
    async def test_sync_filters_non_option_positions(self, adapter, mock_client):
        equity_pos = MagicMock()
        equity_pos.symbol = "AAPL"
        equity_pos.instrument_type = "EQUITY"
        equity_pos.quantity = "100"

        option_pos = MagicMock()
        option_pos.symbol = "AAPL250321C00200000"
        option_pos.instrument_type = "OPTION"
        option_pos.quantity = "5"
        option_pos.average_price = "3.50"
        option_pos.market_value = "1750.0"
        option_pos.unrealized_pnl = "250.0"

        mock_portfolio = MagicMock()
        mock_portfolio.positions = [equity_pos, option_pos]
        mock_client.get_option_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()
        assert len(adapter._positions) == 1
        assert adapter._positions[0].symbol == "AAPL250321C00200000"

    @pytest.mark.asyncio
    async def test_sync_empty_portfolio(self, adapter, mock_client):
        mock_portfolio = MagicMock()
        mock_portfolio.positions = []
        mock_client.get_option_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()
        assert adapter._positions == []

    @pytest.mark.asyncio
    async def test_sync_no_positions_attr(self, adapter, mock_client):
        mock_portfolio = MagicMock(spec=[])
        mock_client.get_option_portfolio.return_value = mock_portfolio

        await adapter.sync_portfolio()
        assert adapter._positions == []

    @pytest.mark.asyncio
    async def test_sync_error_handled(self, adapter, mock_client):
        mock_client.get_option_portfolio.side_effect = RuntimeError("network error")
        await adapter.sync_portfolio()


# ══════════════════════════════════════════════════════════════════════
# 5. Options Routing through OrderRouter
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def options_adapter_mock():
    adapter = AsyncMock()
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    adapter.submit_order = AsyncMock(return_value={"id": "opt-1"})
    adapter.cancel_order = AsyncMock(return_value=None)
    adapter.get_positions = AsyncMock(
        return_value=[Position(symbol="AAPL250321C00200000", quantity=Decimal("5"))]
    )
    adapter.get_account = AsyncMock(return_value={"options_bp": 10_000})
    adapter.submit_multileg_order = AsyncMock(return_value={"id": "ml-1"})
    adapter.cancel_option_order = AsyncMock(return_value=None)
    adapter.get_option_positions = AsyncMock(
        return_value=[Position(symbol="AAPL250321C00200000", quantity=Decimal("5"))]
    )
    adapter.preflight_option_order = AsyncMock(return_value={"status": "ok"})
    adapter.get_option_chain = AsyncMock(return_value={"chain": []})
    adapter.get_option_expirations = AsyncMock(return_value=["2025-03-21"])
    return adapter


@pytest.fixture
def router_with_options(options_adapter_mock):
    r = OrderRouter()
    r.register(AssetClass.OPTION, options_adapter_mock)
    return r


class TestOptionsRouting:
    @pytest.mark.asyncio
    async def test_submit_option_order_routes(
        self, router_with_options, options_adapter_mock
    ):
        order = _make_option_order()
        result = await router_with_options.submit_order(order)
        options_adapter_mock.submit_order.assert_awaited_once_with(order)
        assert result == {"id": "opt-1"}

    @pytest.mark.asyncio
    async def test_submit_multileg_routes(
        self, router_with_options, options_adapter_mock
    ):
        legs = [_make_option_order(), _make_option_order(side=OrderSide.SELL)]
        ml = MultiLegOrder(legs=legs, strategy_type="spread")
        result = await router_with_options.submit_multileg_order(ml)
        options_adapter_mock.submit_multileg_order.assert_awaited_once_with(ml)
        assert result == {"id": "ml-1"}

    @pytest.mark.asyncio
    async def test_cancel_option_order_routes(
        self, router_with_options, options_adapter_mock
    ):
        await router_with_options.cancel_option_order("opt-1")
        options_adapter_mock.cancel_option_order.assert_awaited_once_with("opt-1")

    @pytest.mark.asyncio
    async def test_get_option_positions_routes(
        self, router_with_options, options_adapter_mock
    ):
        positions = await router_with_options.get_option_positions()
        options_adapter_mock.get_option_positions.assert_awaited_once()
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_preflight_routes(
        self, router_with_options, options_adapter_mock
    ):
        order = _make_option_order()
        result = await router_with_options.preflight_option_order(order)
        options_adapter_mock.preflight_option_order.assert_awaited_once_with(order)
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_option_chain_routes(
        self, router_with_options, options_adapter_mock
    ):
        result = await router_with_options.get_option_chain("AAPL")
        options_adapter_mock.get_option_chain.assert_awaited_once_with("AAPL")
        assert result == {"chain": []}

    @pytest.mark.asyncio
    async def test_get_option_expirations_routes(
        self, router_with_options, options_adapter_mock
    ):
        result = await router_with_options.get_option_expirations("AAPL")
        options_adapter_mock.get_option_expirations.assert_awaited_once_with("AAPL")
        assert result == ["2025-03-21"]

    @pytest.mark.asyncio
    async def test_no_option_adapter_raises(self):
        r = OrderRouter()
        with pytest.raises(ValueError, match="No adapter registered"):
            await r.submit_multileg_order(
                MultiLegOrder(legs=[_make_option_order()], strategy_type="test")
            )

    @pytest.mark.asyncio
    async def test_no_option_adapter_cancel_raises(self):
        r = OrderRouter()
        with pytest.raises(ValueError, match="No adapter registered"):
            await r.cancel_option_order("some-id")

    @pytest.mark.asyncio
    async def test_no_option_adapter_positions_raises(self):
        r = OrderRouter()
        with pytest.raises(ValueError, match="No adapter registered"):
            await r.get_option_positions()

    @pytest.mark.asyncio
    async def test_option_positions_aggregated_in_get_positions(
        self, options_adapter_mock
    ):
        """Options positions should appear when get_positions aggregates all."""
        equity_adapter = AsyncMock()
        equity_adapter.get_positions = AsyncMock(
            return_value=[Position(symbol="AAPL", quantity=Decimal("100"))]
        )
        r = OrderRouter()
        r.register(AssetClass.EQUITY, equity_adapter)
        r.register(AssetClass.OPTION, options_adapter_mock)

        all_positions = await r.get_positions()
        assert len(all_positions) == 2
        symbols = {p.symbol for p in all_positions}
        assert "AAPL" in symbols
        assert "AAPL250321C00200000" in symbols

    @pytest.mark.asyncio
    async def test_connect_disconnect_includes_options(self, options_adapter_mock):
        equity_adapter = AsyncMock()
        equity_adapter.connect = AsyncMock()
        equity_adapter.disconnect = AsyncMock()

        r = OrderRouter()
        r.register(AssetClass.EQUITY, equity_adapter)
        r.register(AssetClass.OPTION, options_adapter_mock)

        await r.connect()
        equity_adapter.connect.assert_awaited_once()
        options_adapter_mock.connect.assert_awaited_once()

        await r.disconnect()
        equity_adapter.disconnect.assert_awaited_once()
        options_adapter_mock.disconnect.assert_awaited_once()
