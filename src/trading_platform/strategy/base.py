"""Strategy base class with full lifecycle hooks.

Strategies extend this base and implement on_quote / on_trade / on_bar / on_signal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from trading_platform.core.events import EventBus
from trading_platform.core.models import Bar, QuoteTick, TradeTick


class Strategy(ABC):
    """Abstract base for trading strategies."""

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.event_bus = event_bus
        self.config = config or {}
        self.context: Any = None  # StrategyContext, injected by StrategyManager
        self.is_active: bool = False

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
