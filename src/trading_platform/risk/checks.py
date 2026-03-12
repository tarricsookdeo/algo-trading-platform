"""Individual risk check implementations."""

from __future__ import annotations

from typing import Any

from trading_platform.core.models import Order, Position
from trading_platform.risk.models import RiskConfig, RiskState


def check_position_size(order: Order, positions: list[Position], config: RiskConfig) -> tuple[bool, str]:
    """Check that order doesn't exceed max position size."""
    existing_qty = 0.0
    for p in positions:
        if p.symbol == order.symbol:
            existing_qty = p.quantity
            break
    new_total = existing_qty + order.quantity
    if new_total > config.max_position_size:
        return False, f"Position size {new_total} exceeds limit {config.max_position_size} for {order.symbol}"
    return True, ""


def check_position_concentration(
    order: Order,
    positions: list[Position],
    config: RiskConfig,
    portfolio_value: float,
) -> tuple[bool, str]:
    """Check that a single position doesn't exceed concentration limit."""
    if portfolio_value <= 0:
        return True, ""
    position_value = 0.0
    for p in positions:
        if p.symbol == order.symbol:
            position_value = p.market_value
            break
    order_value = order.quantity * (order.limit_price or 0.0)
    new_value = position_value + order_value
    concentration = new_value / portfolio_value
    if concentration > config.max_position_concentration:
        return False, f"Concentration {concentration:.1%} exceeds limit {config.max_position_concentration:.1%} for {order.symbol}"
    return True, ""


def check_order_value(order: Order, config: RiskConfig) -> tuple[bool, str]:
    """Check that order value doesn't exceed limit."""
    price = order.limit_price or order.stop_price or 0.0
    value = order.quantity * price
    if value > config.max_order_value:
        return False, f"Order value ${value:,.2f} exceeds limit ${config.max_order_value:,.2f}"
    return True, ""


def check_daily_loss(state: RiskState, config: RiskConfig) -> tuple[bool, str]:
    """Check that daily P&L hasn't breached the loss limit."""
    if state.daily_pnl < config.daily_loss_limit:
        return False, f"Daily P&L ${state.daily_pnl:,.2f} below limit ${config.daily_loss_limit:,.2f}"
    return True, ""


def check_max_open_orders(state: RiskState, config: RiskConfig) -> tuple[bool, str]:
    """Check that we haven't exceeded max open orders."""
    if state.open_order_count >= config.max_open_orders:
        return False, f"Open orders {state.open_order_count} at limit {config.max_open_orders}"
    return True, ""


def check_symbol_allowed(order: Order, config: RiskConfig) -> tuple[bool, str]:
    """Check allowlist/blocklist for the symbol."""
    if config.blocked_symbols and order.symbol in config.blocked_symbols:
        return False, f"Symbol {order.symbol} is blocked"
    if config.allowed_symbols and order.symbol not in config.allowed_symbols:
        return False, f"Symbol {order.symbol} not in allowlist"
    return True, ""


def check_portfolio_drawdown(state: RiskState, config: RiskConfig) -> tuple[bool, str]:
    """Post-trade check: portfolio drawdown from peak."""
    if state.portfolio_peak <= 0:
        return True, ""
    drawdown = (state.portfolio_peak - state.portfolio_value) / state.portfolio_peak
    if drawdown > config.max_portfolio_drawdown:
        return False, f"Portfolio drawdown {drawdown:.1%} exceeds limit {config.max_portfolio_drawdown:.1%}"
    return True, ""


def check_daily_trade_count(state: RiskState, config: RiskConfig) -> tuple[bool, str]:
    """Post-trade check: too many trades in a day."""
    if state.daily_trade_count > config.max_daily_trades:
        return False, f"Daily trade count {state.daily_trade_count} exceeds limit {config.max_daily_trades}"
    return True, ""
