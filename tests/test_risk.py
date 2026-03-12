"""Tests for Phase 6: Risk management (checks, manager, models)."""

from __future__ import annotations

import pytest

from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Order, Position
from trading_platform.risk.checks import (
    check_daily_loss,
    check_daily_trade_count,
    check_max_open_orders,
    check_order_value,
    check_portfolio_drawdown,
    check_position_concentration,
    check_position_size,
    check_symbol_allowed,
)
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig, RiskState, RiskViolation


# ── RiskConfig / RiskState / RiskViolation models ─────────────────────


class TestRiskModels:
    def test_risk_config_defaults(self):
        c = RiskConfig()
        assert c.max_position_size == 1000.0
        assert c.max_order_value == 50000.0
        assert c.daily_loss_limit == -5000.0
        assert c.max_open_orders == 20
        assert c.max_daily_trades == 100
        assert c.max_portfolio_drawdown == 0.15
        assert c.allowed_symbols == []
        assert c.blocked_symbols == []

    def test_risk_config_custom(self):
        c = RiskConfig(max_position_size=500, blocked_symbols=["MEME"])
        assert c.max_position_size == 500
        assert c.blocked_symbols == ["MEME"]

    def test_risk_state_defaults(self):
        s = RiskState()
        assert s.is_halted is False
        assert s.daily_pnl == 0.0
        assert s.portfolio_value == 0.0
        assert s.violations == []

    def test_risk_violation_creation(self):
        v = RiskViolation(check_name="test", message="exceeded limit")
        assert v.check_name == "test"
        assert v.order_id == ""


# ── Individual risk checks ────────────────────────────────────────────


class TestPositionSizeCheck:
    def test_within_limit(self):
        order = Order(symbol="AAPL", quantity=100)
        positions = [Position(symbol="AAPL", quantity=200)]
        config = RiskConfig(max_position_size=1000)
        passed, reason = check_position_size(order, positions, config)
        assert passed is True

    def test_exceeds_limit(self):
        order = Order(symbol="AAPL", quantity=600)
        positions = [Position(symbol="AAPL", quantity=500)]
        config = RiskConfig(max_position_size=1000)
        passed, reason = check_position_size(order, positions, config)
        assert passed is False
        assert "exceeds limit" in reason

    def test_no_existing_position(self):
        order = Order(symbol="AAPL", quantity=500)
        config = RiskConfig(max_position_size=1000)
        passed, _ = check_position_size(order, [], config)
        assert passed is True


class TestPositionConcentrationCheck:
    def test_within_limit(self):
        order = Order(symbol="AAPL", quantity=10, limit_price=100.0)
        positions = [Position(symbol="AAPL", market_value=5000)]
        config = RiskConfig(max_position_concentration=0.10)
        passed, _ = check_position_concentration(order, positions, config, 100000.0)
        assert passed is True

    def test_exceeds_limit(self):
        order = Order(symbol="AAPL", quantity=100, limit_price=100.0)
        positions = [Position(symbol="AAPL", market_value=5000)]
        config = RiskConfig(max_position_concentration=0.10)
        passed, reason = check_position_concentration(order, positions, config, 100000.0)
        assert passed is False
        assert "Concentration" in reason

    def test_zero_portfolio_value(self):
        order = Order(symbol="AAPL", quantity=10, limit_price=100.0)
        config = RiskConfig()
        passed, _ = check_position_concentration(order, [], config, 0.0)
        assert passed is True


class TestOrderValueCheck:
    def test_within_limit(self):
        order = Order(symbol="AAPL", quantity=100, limit_price=150.0)
        config = RiskConfig(max_order_value=50000)
        passed, _ = check_order_value(order, config)
        assert passed is True

    def test_exceeds_limit(self):
        order = Order(symbol="AAPL", quantity=500, limit_price=150.0)
        config = RiskConfig(max_order_value=50000)
        passed, reason = check_order_value(order, config)
        assert passed is False
        assert "exceeds limit" in reason


class TestDailyLossCheck:
    def test_pnl_above_limit(self):
        state = RiskState(daily_pnl=-1000.0)
        config = RiskConfig(daily_loss_limit=-5000.0)
        passed, _ = check_daily_loss(state, config)
        assert passed is True

    def test_pnl_below_limit(self):
        state = RiskState(daily_pnl=-6000.0)
        config = RiskConfig(daily_loss_limit=-5000.0)
        passed, reason = check_daily_loss(state, config)
        assert passed is False
        assert "below limit" in reason


class TestMaxOpenOrdersCheck:
    def test_within_limit(self):
        state = RiskState(open_order_count=10)
        config = RiskConfig(max_open_orders=20)
        passed, _ = check_max_open_orders(state, config)
        assert passed is True

    def test_at_limit(self):
        state = RiskState(open_order_count=20)
        config = RiskConfig(max_open_orders=20)
        passed, reason = check_max_open_orders(state, config)
        assert passed is False
        assert "at limit" in reason


class TestSymbolAllowedCheck:
    def test_no_restrictions(self):
        order = Order(symbol="AAPL")
        config = RiskConfig()
        passed, _ = check_symbol_allowed(order, config)
        assert passed is True

    def test_blocked(self):
        order = Order(symbol="MEME")
        config = RiskConfig(blocked_symbols=["MEME"])
        passed, reason = check_symbol_allowed(order, config)
        assert passed is False
        assert "blocked" in reason

    def test_not_in_allowlist(self):
        order = Order(symbol="TSLA")
        config = RiskConfig(allowed_symbols=["AAPL", "MSFT"])
        passed, reason = check_symbol_allowed(order, config)
        assert passed is False
        assert "not in allowlist" in reason

    def test_in_allowlist(self):
        order = Order(symbol="AAPL")
        config = RiskConfig(allowed_symbols=["AAPL", "MSFT"])
        passed, _ = check_symbol_allowed(order, config)
        assert passed is True


class TestPortfolioDrawdownCheck:
    def test_within_limit(self):
        state = RiskState(portfolio_value=95000, portfolio_peak=100000)
        config = RiskConfig(max_portfolio_drawdown=0.15)
        passed, _ = check_portfolio_drawdown(state, config)
        assert passed is True

    def test_exceeds_limit(self):
        state = RiskState(portfolio_value=80000, portfolio_peak=100000)
        config = RiskConfig(max_portfolio_drawdown=0.15)
        passed, reason = check_portfolio_drawdown(state, config)
        assert passed is False
        assert "drawdown" in reason.lower()

    def test_zero_peak(self):
        state = RiskState(portfolio_value=100000, portfolio_peak=0)
        config = RiskConfig()
        passed, _ = check_portfolio_drawdown(state, config)
        assert passed is True


class TestDailyTradeCountCheck:
    def test_within_limit(self):
        state = RiskState(daily_trade_count=50)
        config = RiskConfig(max_daily_trades=100)
        passed, _ = check_daily_trade_count(state, config)
        assert passed is True

    def test_exceeds_limit(self):
        state = RiskState(daily_trade_count=101)
        config = RiskConfig(max_daily_trades=100)
        passed, reason = check_daily_trade_count(state, config)
        assert passed is False
        assert "exceeds limit" in reason


# ── RiskManager ───────────────────────────────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def risk_manager(bus):
    config = RiskConfig(max_position_size=1000, max_order_value=50000, daily_loss_limit=-5000)
    return RiskManager(config, bus)


@pytest.mark.asyncio
async def test_pre_trade_check_passes(risk_manager):
    order = Order(symbol="AAPL", quantity=100, limit_price=150.0, order_id="o1")
    passed, reason = await risk_manager.pre_trade_check(order, [])
    assert passed is True
    assert reason == ""


@pytest.mark.asyncio
async def test_pre_trade_check_fails_position_size(risk_manager):
    order = Order(symbol="AAPL", quantity=1500, order_id="o2")
    passed, reason = await risk_manager.pre_trade_check(order, [])
    assert passed is False
    assert "exceeds limit" in reason
    assert len(risk_manager.state.violations) == 1


@pytest.mark.asyncio
async def test_pre_trade_check_halted(risk_manager):
    risk_manager.state.is_halted = True
    risk_manager.state.halt_reason = "test halt"
    order = Order(symbol="AAPL", quantity=10, order_id="o3")
    passed, reason = await risk_manager.pre_trade_check(order, [])
    assert passed is False
    assert "halted" in reason.lower()


@pytest.mark.asyncio
async def test_post_trade_check_increments_count(risk_manager):
    risk_manager.state.portfolio_value = 100000
    risk_manager.state.portfolio_peak = 100000
    await risk_manager.post_trade_check()
    assert risk_manager.state.daily_trade_count == 1


@pytest.mark.asyncio
async def test_update_portfolio_value(risk_manager):
    await risk_manager.update_portfolio_value(150000)
    assert risk_manager.state.portfolio_value == 150000
    assert risk_manager.state.portfolio_peak == 150000

    await risk_manager.update_portfolio_value(140000)
    assert risk_manager.state.portfolio_value == 140000
    assert risk_manager.state.portfolio_peak == 150000  # peak unchanged


@pytest.mark.asyncio
async def test_update_daily_pnl_triggers_halt(risk_manager):
    await risk_manager.update_daily_pnl(-6000)
    assert risk_manager.state.is_halted is True
    assert "loss limit" in risk_manager.state.halt_reason.lower()


@pytest.mark.asyncio
async def test_reset_daily(risk_manager):
    risk_manager.state.daily_pnl = -3000
    risk_manager.state.daily_trade_count = 50
    risk_manager.state.is_halted = True
    risk_manager.state.halt_reason = "test"
    await risk_manager.reset_daily()
    assert risk_manager.state.daily_pnl == 0.0
    assert risk_manager.state.daily_trade_count == 0
    assert risk_manager.state.is_halted is False


@pytest.mark.asyncio
async def test_get_risk_state(risk_manager):
    state = risk_manager.get_risk_state()
    assert "is_halted" in state
    assert "daily_pnl" in state
    assert "max_position_size" in state


@pytest.mark.asyncio
async def test_get_violations(risk_manager):
    order = Order(symbol="AAPL", quantity=1500, order_id="v1")
    await risk_manager.pre_trade_check(order, [])
    violations = risk_manager.get_violations()
    assert len(violations) == 1
    assert violations[0]["check_name"] == "pre_trade"


@pytest.mark.asyncio
async def test_halt_publishes_event(bus, risk_manager):
    received = []

    async def handler(ch, ev):
        received.append((ch, ev))

    await bus.subscribe("risk.halt", handler)
    await risk_manager.update_daily_pnl(-6000)
    assert any(ch == "risk.halt" for ch, _ in received)
