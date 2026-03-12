"""StrategyContext provides strategies with access to market data, execution, and portfolio state."""

from __future__ import annotations

from typing import Any

from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Bar, Order, Position, QuoteTick


class StrategyContext:
    """Runtime context injected into each strategy.

    Provides access to market data, order submission, portfolio state,
    and risk validation without strategies needing direct adapter references.
    """

    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        exec_adapter: Any = None,
        risk_manager: Any = None,
    ) -> None:
        self.strategy_id = strategy_id
        self._bus = event_bus
        self._exec = exec_adapter
        self._risk = risk_manager
        self._log = get_logger(f"strategy.context.{strategy_id}")
        self._latest_quotes: dict[str, QuoteTick] = {}
        self._latest_bars: dict[str, Bar] = {}
        self._positions: list[Position] = []

    def update_quote(self, quote: QuoteTick) -> None:
        self._latest_quotes[quote.symbol] = quote

    def update_bar(self, bar: Bar) -> None:
        self._latest_bars[bar.symbol] = bar

    def update_positions(self, positions: list[Position]) -> None:
        self._positions = list(positions)

    def get_latest_quote(self, symbol: str) -> QuoteTick | None:
        return self._latest_quotes.get(symbol)

    def get_latest_bar(self, symbol: str) -> Bar | None:
        return self._latest_bars.get(symbol)

    def get_positions(self) -> list[Position]:
        return list(self._positions)

    async def submit_order(self, order: Order) -> Any:
        """Submit an order through risk checks then execution."""
        if self._risk:
            passed, reason = await self._risk.pre_trade_check(order, self._positions)
            if not passed:
                self._log.warning("order rejected by risk", reason=reason, order_id=order.order_id)
                await self._bus.publish("risk.check.failed", {
                    "strategy_id": self.strategy_id,
                    "order_id": order.order_id,
                    "reason": reason,
                })
                return None
            await self._bus.publish("risk.check.passed", {
                "strategy_id": self.strategy_id,
                "order_id": order.order_id,
            })

        if self._exec:
            return await self._exec.submit_order(order)
        self._log.warning("no exec adapter configured")
        return None

    async def cancel_order(self, order_id: str) -> Any:
        if self._exec:
            return await self._exec.cancel_order(order_id)
        return None
