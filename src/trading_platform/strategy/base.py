"""Strategy base class with lifecycle hooks.

Strategies extend this base and implement on_quote / on_trade / on_bar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from trading_platform.core.events import EventBus
from trading_platform.core.models import Bar, QuoteTick, TradeTick


class Strategy(ABC):
    """Abstract base for trading strategies."""

    def __init__(self, name: str, event_bus: EventBus) -> None:
        self.name = name
        self.event_bus = event_bus

    async def start(self) -> None:
        """Called when the platform starts. Override for setup logic."""

    async def stop(self) -> None:
        """Called on platform shutdown. Override for cleanup logic."""

    @abstractmethod
    async def on_quote(self, quote: QuoteTick) -> None: ...

    @abstractmethod
    async def on_trade(self, trade: TradeTick) -> None: ...

    @abstractmethod
    async def on_bar(self, bar: Bar) -> None: ...
