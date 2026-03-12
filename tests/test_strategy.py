"""Tests for Phase 5: Strategy framework (base, context, manager, SMA crossover)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Bar, Order, Position, QuoteTick, TradeTick
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig
from trading_platform.strategy.base import Strategy
from trading_platform.strategy.context import StrategyContext
from trading_platform.strategy.examples.sma_crossover import SMACrossoverStrategy
from trading_platform.strategy.manager import StrategyManager, StrategyState


# ── Concrete strategy for testing ─────────────────────────────────────


class DummyStrategy(Strategy):
    """Minimal strategy implementation for tests."""

    def __init__(self, name: str, event_bus: EventBus) -> None:
        super().__init__(name, event_bus)
        self.quotes_seen: list[QuoteTick] = []
        self.trades_seen: list[TradeTick] = []
        self.bars_seen: list[Bar] = []

    async def on_quote(self, quote: QuoteTick) -> None:
        self.quotes_seen.append(quote)

    async def on_trade(self, trade: TradeTick) -> None:
        self.trades_seen.append(trade)

    async def on_bar(self, bar: Bar) -> None:
        self.bars_seen.append(bar)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def dummy_strategy(bus):
    return DummyStrategy("test_strat", bus)


@pytest.fixture
def mock_exec():
    m = AsyncMock()
    m.submit_order = AsyncMock(return_value={"order_id": "mock-123"})
    m.cancel_order = AsyncMock(return_value=None)
    return m


def _make_quote(symbol: str = "AAPL") -> QuoteTick:
    return QuoteTick(
        symbol=symbol,
        bid_price=150.0,
        bid_size=100,
        ask_price=150.05,
        ask_size=200,
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


def _make_trade(symbol: str = "AAPL") -> TradeTick:
    return TradeTick(
        symbol=symbol,
        price=150.25,
        size=10,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )


# ── StrategyContext tests ─────────────────────────────────────────────


class TestStrategyContext:
    def test_update_and_get_quote(self, bus):
        ctx = StrategyContext("s1", bus)
        q = _make_quote()
        ctx.update_quote(q)
        assert ctx.get_latest_quote("AAPL") is q
        assert ctx.get_latest_quote("MSFT") is None

    def test_update_and_get_bar(self, bus):
        ctx = StrategyContext("s1", bus)
        b = _make_bar()
        ctx.update_bar(b)
        assert ctx.get_latest_bar("AAPL") is b

    def test_update_and_get_positions(self, bus):
        ctx = StrategyContext("s1", bus)
        pos = [Position(symbol="AAPL", quantity=100)]
        ctx.update_positions(pos)
        result = ctx.get_positions()
        assert len(result) == 1
        assert result[0].symbol == "AAPL"
        # Verify it returns a copy
        result.clear()
        assert len(ctx.get_positions()) == 1

    @pytest.mark.asyncio
    async def test_submit_order_no_risk_no_exec(self, bus):
        ctx = StrategyContext("s1", bus)
        order = Order(symbol="AAPL", quantity=100)
        result = await ctx.submit_order(order)
        assert result is None

    @pytest.mark.asyncio
    async def test_submit_order_with_exec(self, bus, mock_exec):
        ctx = StrategyContext("s1", bus, exec_adapter=mock_exec)
        order = Order(symbol="AAPL", quantity=100)
        result = await ctx.submit_order(order)
        assert result == {"order_id": "mock-123"}
        mock_exec.submit_order.assert_awaited_once_with(order)

    @pytest.mark.asyncio
    async def test_submit_order_risk_rejection(self, bus, mock_exec):
        config = RiskConfig(max_position_size=50)
        rm = RiskManager(config, bus)
        ctx = StrategyContext("s1", bus, exec_adapter=mock_exec, risk_manager=rm)
        order = Order(symbol="AAPL", quantity=100, order_id="rej-1")
        result = await ctx.submit_order(order)
        assert result is None
        mock_exec.submit_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submit_order_risk_passes(self, bus, mock_exec):
        config = RiskConfig(max_position_size=1000)
        rm = RiskManager(config, bus)
        ctx = StrategyContext("s1", bus, exec_adapter=mock_exec, risk_manager=rm)
        order = Order(symbol="AAPL", quantity=100, order_id="pass-1")
        result = await ctx.submit_order(order)
        assert result is not None
        mock_exec.submit_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_order(self, bus, mock_exec):
        ctx = StrategyContext("s1", bus, exec_adapter=mock_exec)
        await ctx.cancel_order("order-123")
        mock_exec.cancel_order.assert_awaited_once_with("order-123")


# ── StrategyManager tests ─────────────────────────────────────────────


class TestStrategyManager:
    def test_register(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        info = sm.get_strategy_info()
        assert len(info) == 1
        assert info[0]["strategy_id"] == "test_strat"
        assert info[0]["state"] == "registered"

    def test_register_duplicate(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        sm.register(dummy_strategy)
        assert len(sm.get_strategy_info()) == 1

    def test_deregister(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        sm.deregister("test_strat")
        assert len(sm.get_strategy_info()) == 0

    @pytest.mark.asyncio
    async def test_start_stop_strategy(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)

        await sm.start_strategy("test_strat")
        entry = sm.get_strategy_entry("test_strat")
        assert entry.state == StrategyState.ACTIVE
        assert dummy_strategy.is_active is True

        await sm.stop_strategy("test_strat")
        assert entry.state == StrategyState.STOPPED
        assert dummy_strategy.is_active is False

    @pytest.mark.asyncio
    async def test_start_nonexistent(self, bus):
        sm = StrategyManager(bus)
        await sm.start_strategy("missing")  # should not raise

    @pytest.mark.asyncio
    async def test_start_all_stop_all(self, bus):
        s1 = DummyStrategy("s1", bus)
        s2 = DummyStrategy("s2", bus)
        sm = StrategyManager(bus)
        sm.register(s1)
        sm.register(s2)
        await sm.start_all()
        info = sm.get_strategy_info()
        assert all(i["state"] == "active" for i in info)
        await sm.stop_all()
        info = sm.get_strategy_info()
        assert all(i["state"] == "stopped" for i in info)

    @pytest.mark.asyncio
    async def test_dispatch_quote(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        await sm.start_strategy("test_strat")
        q = _make_quote()
        await sm.dispatch_quote("quote", q)
        assert len(dummy_strategy.quotes_seen) == 1

    @pytest.mark.asyncio
    async def test_dispatch_trade(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        await sm.start_strategy("test_strat")
        t = _make_trade()
        await sm.dispatch_trade("trade", t)
        assert len(dummy_strategy.trades_seen) == 1

    @pytest.mark.asyncio
    async def test_dispatch_bar(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        await sm.start_strategy("test_strat")
        b = _make_bar()
        await sm.dispatch_bar("bar", b)
        assert len(dummy_strategy.bars_seen) == 1

    @pytest.mark.asyncio
    async def test_dispatch_skips_inactive(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        # Don't start — state is REGISTERED
        await sm.dispatch_quote("quote", _make_quote())
        assert len(dummy_strategy.quotes_seen) == 0

    @pytest.mark.asyncio
    async def test_wire_events(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        await sm.start_strategy("test_strat")
        await sm.wire_events()

        # Publishing to bus should reach strategy
        await bus.publish("quote", _make_quote())
        assert len(dummy_strategy.quotes_seen) == 1

        await sm.unwire_events()

    @pytest.mark.asyncio
    async def test_dispatch_position_update(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        await sm.start_strategy("test_strat")

        await sm.dispatch_position_update("execution.portfolio.update", {
            "positions": [{"symbol": "AAPL", "quantity": 100}],
        })
        ctx = sm.get_strategy_entry("test_strat").context
        assert len(ctx.get_positions()) == 1

    @pytest.mark.asyncio
    async def test_strategy_lifecycle_events(self, bus, dummy_strategy):
        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe("strategy.lifecycle", handler)
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        await sm.start_strategy("test_strat")
        assert any(e["action"] == "started" for e in received)
        await sm.stop_strategy("test_strat")
        assert any(e["action"] == "stopped" for e in received)

    def test_get_strategy_info_metrics(self, bus, dummy_strategy):
        sm = StrategyManager(bus)
        sm.register(dummy_strategy)
        entry = sm.get_strategy_entry("test_strat")
        entry.wins = 3
        entry.losses = 7
        entry.pnl = 500.0
        info = sm.get_strategy_info()
        assert info[0]["win_rate"] == 0.3
        assert info[0]["pnl"] == 500.0


# ── SMACrossoverStrategy tests ────────────────────────────────────────


class TestSMACrossover:
    @pytest.fixture
    def sma_strategy(self, bus):
        return SMACrossoverStrategy(
            "sma_test",
            bus,
            config={"short_window": 3, "long_window": 5, "symbols": ["AAPL"], "quantity": 10},
        )

    def test_init(self, sma_strategy):
        assert sma_strategy.short_window == 3
        assert sma_strategy.long_window == 5
        assert sma_strategy.quantity == 10

    @pytest.mark.asyncio
    async def test_on_start_clears_state(self, sma_strategy):
        sma_strategy._prices["AAPL"].append(100.0)
        await sma_strategy.on_start()
        assert len(sma_strategy._prices) == 0

    @pytest.mark.asyncio
    async def test_ignores_unmatched_symbol(self, sma_strategy, bus):
        bar = _make_bar(symbol="MSFT", close=100.0)
        await sma_strategy.on_bar(bar)
        assert len(sma_strategy._prices["MSFT"]) == 0

    @pytest.mark.asyncio
    async def test_accumulates_prices(self, sma_strategy, bus):
        for i in range(4):
            bar = _make_bar(symbol="AAPL", close=100.0 + i)
            await sma_strategy.on_bar(bar)
        assert len(sma_strategy._prices["AAPL"]) == 4

    @pytest.mark.asyncio
    async def test_generates_buy_signal(self, bus):
        """Feed prices that create an upward crossover."""
        signals = []

        async def capture(ch, ev):
            if ch == "strategy.signal":
                signals.append(ev)

        await bus.subscribe("strategy.signal", capture)

        strategy = SMACrossoverStrategy(
            "sma_buy",
            bus,
            config={"short_window": 2, "long_window": 3, "symbols": ["AAPL"], "quantity": 10},
        )
        strategy.context = AsyncMock()
        strategy.context.submit_order = AsyncMock(return_value=None)

        # Feed 3 declining bars (sets long SMA), then rising
        prices = [100, 99, 98, 102, 105]
        for p in prices:
            bar = _make_bar(symbol="AAPL", close=p)
            await strategy.on_bar(bar)

        # Should have generated at least one signal
        assert len(signals) > 0

    @pytest.mark.asyncio
    async def test_on_signal_no_context(self, sma_strategy):
        """on_signal should not raise without context."""
        await sma_strategy.on_signal({"symbol": "AAPL", "side": "buy"})
