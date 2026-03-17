"""RiskManager runs pre-trade and post-trade risk checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trading_platform.core.enums import AssetClass
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

_TERMINAL_ORDER_EVENTS = {"execution.order.filled", "execution.order.cancelled", "execution.order.rejected"}


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
        # Optional greeks risk components (set via register_greeks_checks)
        self._greeks_provider: Any | None = None
        self._greeks_config: Any | None = None

    async def wire_events(self, event_bus: EventBus) -> None:
        """Subscribe to execution events to keep risk state current automatically."""
        self._event_bus = event_bus
        await event_bus.subscribe("execution.order.submitted", self._on_order_submitted)
        await event_bus.subscribe("execution.order.filled", self._on_order_terminal)
        await event_bus.subscribe("execution.order.cancelled", self._on_order_terminal)
        await event_bus.subscribe("execution.order.rejected", self._on_order_terminal)
        await event_bus.subscribe("execution.portfolio.update", self._on_portfolio_update)

    async def unwire_events(self, event_bus: EventBus) -> None:
        """Unsubscribe from execution events."""
        await event_bus.unsubscribe("execution.order.submitted", self._on_order_submitted)
        await event_bus.unsubscribe("execution.order.filled", self._on_order_terminal)
        await event_bus.unsubscribe("execution.order.cancelled", self._on_order_terminal)
        await event_bus.unsubscribe("execution.order.rejected", self._on_order_terminal)
        await event_bus.unsubscribe("execution.portfolio.update", self._on_portfolio_update)

    async def _on_order_submitted(self, channel: str, event: Any) -> None:
        self.state.open_order_count += 1

    async def _on_order_terminal(self, channel: str, event: Any) -> None:
        self.state.open_order_count = max(0, self.state.open_order_count - 1)
        if channel == "execution.order.filled":
            await self.post_trade_check()

    async def _on_portfolio_update(self, channel: str, event: Any) -> None:
        if not isinstance(event, dict):
            return
        positions = event.get("positions", [])
        if positions:
            total_value = sum(
                float(p.get("market_value", 0) if isinstance(p, dict) else getattr(p, "market_value", 0))
                for p in positions
            )
            if total_value > 0:
                await self.update_portfolio_value(total_value)
        account = event.get("account", {})
        if account:
            # Use total buying power as a proxy for daily P&L tracking when available
            bp = account.get("buying_power")
            if bp is not None:
                pass  # buying_power alone isn't P&L — leave daily_pnl for explicit updates

    def register_greeks_checks(self, provider: Any, greeks_config: Any) -> None:
        """Register a GreeksProvider and GreeksRiskConfig for options checks."""
        self._greeks_provider = provider
        self._greeks_config = greeks_config

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

        # Run greeks checks for options orders when configured
        if (
            self._greeks_provider is not None
            and self._greeks_config is not None
            and order.asset_class == AssetClass.OPTION
        ):
            greeks_result = await self._run_greeks_checks(order, positions)
            if not greeks_result[0]:
                return greeks_result

        return True, ""

    async def _run_greeks_checks(
        self, order: Order, positions: list[Position]
    ) -> tuple[bool, str]:
        """Run all configured greeks risk checks."""
        from trading_platform.risk.greeks_checks import (
            check_portfolio_delta,
            check_portfolio_gamma,
            check_single_position_greeks,
            check_theta_decay,
            check_vega_exposure,
        )

        provider = self._greeks_provider
        config = self._greeks_config

        # Filter to positions with symbol and quantity
        option_positions = [
            p for p in positions if p.symbol and p.quantity
        ]

        # Build check callables to avoid eagerly creating coroutines
        # (unawaited coroutines trigger RuntimeWarning on early-exit)
        checks = [
            lambda: check_portfolio_delta(provider, option_positions, config),
            lambda: check_portfolio_gamma(provider, option_positions, config),
            lambda: check_theta_decay(provider, option_positions, config),
            lambda: check_vega_exposure(provider, option_positions, config),
            lambda: check_single_position_greeks(provider, order, config),
        ]

        for check_fn in checks:
            passed, reason = await check_fn()
            if not passed:
                violation = RiskViolation(
                    check_name="greeks",
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
                self._log.warning(
                    "greeks risk check failed",
                    reason=reason,
                    order_id=order.order_id,
                )
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
