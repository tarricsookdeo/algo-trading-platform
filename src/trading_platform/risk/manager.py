"""RiskManager runs pre-trade and post-trade risk checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
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
from trading_platform.risk.models import RiskConfig, RiskState, RiskViolation


class RiskManager:
    """Manages pre-trade and post-trade risk checks.

    Sits between Strategy and ExecAdapter. Strategies submit orders
    through StrategyContext which calls pre_trade_check before execution.
    """

    def __init__(self, config: RiskConfig, event_bus: EventBus) -> None:
        self.config = config
        self._bus = event_bus
        self._log = get_logger("risk.manager")
        self.state = RiskState()

    async def pre_trade_check(self, order: Order, positions: list[Position]) -> tuple[bool, str]:
        """Run all pre-trade checks. Returns (passed, reason)."""
        if self.state.is_halted:
            return False, f"Trading halted: {self.state.halt_reason}"

        checks = [
            check_symbol_allowed(order, self.config),
            check_position_size(order, positions, self.config),
            check_position_concentration(order, positions, self.config, self.state.portfolio_value),
            check_order_value(order, self.config),
            check_daily_loss(self.state, self.config),
            check_max_open_orders(self.state, self.config),
        ]

        for passed, reason in checks:
            if not passed:
                violation = RiskViolation(
                    check_name="pre_trade",
                    message=reason,
                    order_id=order.order_id,
                    symbol=order.symbol,
                    timestamp=datetime.now(UTC),
                )
                self.state.violations.append(violation)
                await self._bus.publish("risk.check.failed", {
                    "order_id": order.order_id,
                    "reason": reason,
                })
                self._log.warning("pre-trade check failed", reason=reason, order_id=order.order_id)
                return False, reason

        return True, ""

    async def post_trade_check(self) -> None:
        """Run post-trade checks and emit alerts/halts as needed."""
        self.state.daily_trade_count += 1

        # Drawdown check
        passed, reason = check_portfolio_drawdown(self.state, self.config)
        if not passed:
            await self._halt(reason)
            return

        # Trade count check
        passed, reason = check_daily_trade_count(self.state, self.config)
        if not passed:
            await self._bus.publish("risk.alert", {
                "type": "daily_trade_count",
                "message": reason,
                "trade_count": self.state.daily_trade_count,
            })
            self._log.warning("risk alert: trade count", reason=reason)

    async def update_portfolio_value(self, value: float) -> None:
        """Update portfolio value and peak for drawdown tracking."""
        self.state.portfolio_value = value
        if value > self.state.portfolio_peak:
            self.state.portfolio_peak = value

    async def update_daily_pnl(self, pnl: float) -> None:
        """Update daily P&L."""
        self.state.daily_pnl = pnl
        if pnl < self.config.daily_loss_limit:
            await self._halt(f"Daily loss limit breached: ${pnl:,.2f}")

    def update_open_order_count(self, count: int) -> None:
        self.state.open_order_count = count

    async def reset_daily(self) -> None:
        """Reset daily counters (call at start of trading day)."""
        self.state.daily_pnl = 0.0
        self.state.daily_trade_count = 0
        self.state.is_halted = False
        self.state.halt_reason = ""
        self._log.info("daily risk counters reset")

    async def _halt(self, reason: str) -> None:
        """Halt all trading."""
        self.state.is_halted = True
        self.state.halt_reason = reason
        violation = RiskViolation(
            check_name="halt",
            message=reason,
            timestamp=datetime.now(UTC),
        )
        self.state.violations.append(violation)
        await self._bus.publish("risk.halt", {"reason": reason})
        self._log.error("TRADING HALTED", reason=reason)

    def get_risk_state(self) -> dict[str, Any]:
        """Return current risk state as a dict for the dashboard."""
        return {
            "is_halted": self.state.is_halted,
            "halt_reason": self.state.halt_reason,
            "daily_pnl": self.state.daily_pnl,
            "daily_trade_count": self.state.daily_trade_count,
            "portfolio_value": self.state.portfolio_value,
            "portfolio_peak": self.state.portfolio_peak,
            "open_order_count": self.state.open_order_count,
            "max_position_size": self.config.max_position_size,
            "max_order_value": self.config.max_order_value,
            "daily_loss_limit": self.config.daily_loss_limit,
            "max_portfolio_drawdown": self.config.max_portfolio_drawdown,
        }

    def get_violations(self) -> list[dict[str, Any]]:
        """Return violation history."""
        return [v.model_dump(mode="json") for v in self.state.violations]
