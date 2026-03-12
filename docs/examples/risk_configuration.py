"""Risk configuration and testing example.

Demonstrates how to:
1. Create a RiskConfig with custom limits
2. Initialize a RiskManager
3. Run pre-trade checks against sample orders
4. Update portfolio state and trigger halts
5. Inspect violations and risk state

This example runs entirely offline — no broker connections required.

Usage:
    python docs/examples/risk_configuration.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.core.models import Order, Position
from trading_platform.risk.checks import (
    check_daily_loss,
    check_order_value,
    check_position_concentration,
    check_position_size,
    check_symbol_allowed,
)
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig, RiskState


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.risk")

    # ── 1. Configure risk limits ───────────────────────────────────────
    config = RiskConfig(
        max_position_size=500.0,           # max 500 shares per symbol
        max_position_concentration=0.10,    # max 10% of portfolio in one name
        max_order_value=25000.0,            # max $25k per order
        daily_loss_limit=-2500.0,           # halt if daily P&L < -$2,500
        max_open_orders=15,
        max_daily_trades=75,
        max_portfolio_drawdown=0.10,        # halt on 10% drawdown
        blocked_symbols=["GME", "AMC"],     # symbols we won't trade
        allowed_symbols=[],                 # empty = allow all non-blocked
    )
    print("Risk configuration:")
    print(f"  Max position size: {config.max_position_size}")
    print(f"  Max order value: ${config.max_order_value:,.2f}")
    print(f"  Daily loss limit: ${config.daily_loss_limit:,.2f}")
    print(f"  Max drawdown: {config.max_portfolio_drawdown:.0%}")
    print(f"  Blocked symbols: {config.blocked_symbols}")
    print()

    # ── 2. Initialize risk manager ─────────────────────────────────────
    event_bus = EventBus()
    manager = RiskManager(config, event_bus)

    # Set initial portfolio state
    await manager.update_portfolio_value(100_000.0)
    await manager.update_daily_pnl(0.0)
    manager.update_open_order_count(2)

    # ── 3. Test individual risk checks ─────────────────────────────────
    print("=" * 60)
    print("Individual risk checks")
    print("=" * 60)

    positions = [
        Position(symbol="AAPL", quantity=200.0, avg_entry_price=150.0, market_value=30_000.0),
        Position(symbol="MSFT", quantity=100.0, avg_entry_price=400.0, market_value=40_000.0),
    ]

    # Check: position size (will pass — 200 + 100 = 300 < 500)
    order_ok = Order(symbol="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100.0)
    passed, reason = check_position_size(order_ok, positions, config)
    print(f"Position size (AAPL +100): {'PASS' if passed else 'FAIL'} {reason}")

    # Check: position size (will fail — 200 + 400 = 600 > 500)
    order_big = Order(symbol="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=400.0)
    passed, reason = check_position_size(order_big, positions, config)
    print(f"Position size (AAPL +400): {'PASS' if passed else 'FAIL'} {reason}")

    # Check: blocked symbol
    order_blocked = Order(symbol="GME", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0)
    passed, reason = check_symbol_allowed(order_blocked, config)
    print(f"Symbol allowed (GME): {'PASS' if passed else 'FAIL'} {reason}")

    # Check: order value (will pass)
    order_limit = Order(symbol="AAPL", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=100.0, limit_price=150.0)
    passed, reason = check_order_value(order_limit, config)
    print(f"Order value ($15,000): {'PASS' if passed else 'FAIL'} {reason}")

    # Check: order value (will fail — 200 × $150 = $30,000 > $25,000)
    order_expensive = Order(symbol="AAPL", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=200.0, limit_price=150.0)
    passed, reason = check_order_value(order_expensive, config)
    print(f"Order value ($30,000): {'PASS' if passed else 'FAIL'} {reason}")

    # Check: concentration (30k + 15k = 45k / 100k = 45% > 10%)
    passed, reason = check_position_concentration(order_limit, positions, config, 100_000.0)
    print(f"Concentration (AAPL 45%): {'PASS' if passed else 'FAIL'} {reason}")

    print()

    # ── 4. Full pre-trade check via RiskManager ────────────────────────
    print("=" * 60)
    print("Full pre-trade checks via RiskManager")
    print("=" * 60)

    # This order should pass all checks
    good_order = Order(
        symbol="GOOGL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10.0,
        limit_price=170.0,
    )
    passed, reason = await manager.pre_trade_check(good_order, positions)
    print(f"GOOGL buy 10 @ $170: {'PASS' if passed else 'FAIL'} {reason}")

    # This order should fail (blocked symbol)
    bad_order = Order(
        symbol="GME",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10.0,
    )
    passed, reason = await manager.pre_trade_check(bad_order, positions)
    print(f"GME buy 10: {'PASS' if passed else 'FAIL'} {reason}")

    print()

    # ── 5. Simulate daily loss triggering a halt ───────────────────────
    print("=" * 60)
    print("Trading halt simulation")
    print("=" * 60)

    # Simulate losses accumulating
    await manager.update_daily_pnl(-1000.0)
    state = manager.get_risk_state()
    print(f"Daily P&L: ${state['daily_pnl']:,.2f} — Halted: {state['is_halted']}")

    await manager.update_daily_pnl(-2000.0)
    state = manager.get_risk_state()
    print(f"Daily P&L: ${state['daily_pnl']:,.2f} — Halted: {state['is_halted']}")

    # This should trigger the halt
    await manager.update_daily_pnl(-3000.0)
    state = manager.get_risk_state()
    print(f"Daily P&L: ${state['daily_pnl']:,.2f} — Halted: {state['is_halted']} — Reason: {state['halt_reason']}")

    # Orders are rejected during a halt
    passed, reason = await manager.pre_trade_check(good_order, positions)
    print(f"Order during halt: {'PASS' if passed else 'FAIL'} {reason}")

    # Reset to resume trading
    await manager.reset_daily()
    state = manager.get_risk_state()
    print(f"After reset — Halted: {state['is_halted']}, Daily P&L: ${state['daily_pnl']:,.2f}")

    print()

    # ── 6. View violations ─────────────────────────────────────────────
    print("=" * 60)
    print("Risk violations")
    print("=" * 60)
    for v in manager.get_violations():
        print(f"  [{v['check_name']}] {v['message']}")


if __name__ == "__main__":
    asyncio.run(main())
