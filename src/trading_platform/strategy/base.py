"""Strategy base class with full lifecycle hooks.

Strategies extend this base and implement on_quote / on_trade / on_bar / on_signal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from trading_platform.core.events import EventBus
from trading_platform.core.models import Bar, QuoteTick, TradeTick

_ZERO = Decimal("0")


class Strategy(ABC):
    """Abstract base for trading strategies."""

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.event_bus = event_bus
        self.config = config or {}
        self.context: Any = None  # StrategyContext, injected by StrategyManager
        self.is_active: bool = False

        # Conditional evaluation gate
        self.min_price_change: Decimal = Decimal(str(self.config.get("min_price_change", 0)))
        self.min_price_change_percent: Decimal = Decimal(str(self.config.get("min_price_change_percent", 0)))
        self._last_eval_prices: dict[str, Decimal] = {}
        self.evaluations_skipped: int = 0
        self.evaluations_run: int = 0

    def _should_evaluate(self, symbol: str, current_price: Decimal) -> bool:
        """Check if the strategy should evaluate for the given price.

        Returns True if evaluation should proceed, False to skip.
        """
        if self.min_price_change == _ZERO and self.min_price_change_percent == _ZERO:
            return True  # no gate, always evaluate

        last_price = self._last_eval_prices.get(symbol)
        if last_price is None:
            return True  # first tick, always evaluate

        abs_change = abs(current_price - last_price)

        if self.min_price_change != _ZERO and abs_change >= self.min_price_change:
            return True
        if self.min_price_change_percent != _ZERO and last_price != _ZERO:
            pct_change = abs_change / last_price
            if pct_change >= self.min_price_change_percent:
                return True

        return False

    def _record_evaluation(self, symbol: str, price: Decimal) -> None:
        """Update last evaluated price for a symbol."""
        self._last_eval_prices[symbol] = price
        self.evaluations_run += 1

    @property
    def skip_rate_percent(self) -> float:
        """Percentage of evaluations skipped due to the price change gate."""
        total = self.evaluations_run + self.evaluations_skipped
        if total == 0:
            return 0.0
        return (self.evaluations_skipped / total) * 100.0

    async def on_start(self) -> None:
        """Called when the strategy is started. Override for setup logic."""

    async def on_stop(self) -> None:
        """Called when the strategy is stopped. Override for cleanup logic."""

    @abstractmethod
    async def on_quote(self, quote: QuoteTick) -> None: ...

    @abstractmethod
    async def on_trade(self, trade: TradeTick) -> None: ...

    @abstractmethod
    async def on_bar(self, bar: Bar) -> None: ...

    async def on_order_update(self, order_update: Any) -> None:
        """Called when an order status changes. Override to handle."""

    async def on_position_update(self, positions: list[Any]) -> None:
        """Called when positions are updated. Override to handle."""

    async def on_signal(self, signal: Any) -> None:
        """Called when the strategy generates a signal. Override to implement trading logic."""
