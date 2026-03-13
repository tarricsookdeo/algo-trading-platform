"""StrategyContext provides strategies with access to market data, execution, and portfolio state."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from trading_platform.core.enums import OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Bar, Order, Position, QuoteTick

if TYPE_CHECKING:
    from trading_platform.bracket.manager import BracketOrderManager
    from trading_platform.bracket.models import BracketOrder


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
        bracket_manager: "BracketOrderManager | None" = None,
    ) -> None:
        self.strategy_id = strategy_id
        self._bus = event_bus
        self._exec = exec_adapter
        self._risk = risk_manager
        self._bracket = bracket_manager
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

    async def submit_bracket_order(
        self,
        symbol: str,
        quantity: Decimal,
        entry_type: OrderType,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        entry_limit_price: Decimal | None = None,
    ) -> "BracketOrder | None":
        """Submit a bracket order through the BracketOrderManager."""
        if not self._bracket:
            self._log.warning("no bracket manager configured")
            return None
        return await self._bracket.submit_bracket_order(
            symbol=symbol,
            quantity=quantity,
            entry_type=entry_type,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            entry_limit_price=entry_limit_price,
        )

    async def cancel_bracket_order(self, bracket_id: str) -> bool:
        """Cancel a bracket order."""
        if not self._bracket:
            return False
        return await self._bracket.cancel_bracket(bracket_id)
