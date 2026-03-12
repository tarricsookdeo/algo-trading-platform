"""Example SMA crossover strategy.

Subscribes to bars, computes short/long SMA, and generates BUY/SELL signals.
This is for documentation and testing — NOT for live trading.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Bar, Order, QuoteTick, TradeTick
from trading_platform.strategy.base import Strategy


class SMACrossoverStrategy(Strategy):
    """Simple Moving Average crossover strategy.

    Config:
        short_window: int — SMA short period (default 10)
        long_window: int — SMA long period (default 30)
        symbols: list[str] — symbols to trade
        quantity: float — shares per trade (default 100)
    """

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, event_bus, config)
        self.short_window: int = self.config.get("short_window", 10)
        self.long_window: int = self.config.get("long_window", 30)
        self.symbols: list[str] = self.config.get("symbols", [])
        self.quantity: float = self.config.get("quantity", 100.0)
        self._prices: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.long_window))
        self._position_side: dict[str, str] = {}  # symbol -> "long" | "short" | ""

    async def on_start(self) -> None:
        self._prices.clear()
        self._position_side.clear()

    async def on_quote(self, quote: QuoteTick) -> None:
        pass

    async def on_trade(self, trade: TradeTick) -> None:
        pass

    async def on_bar(self, bar: Bar) -> None:
        if self.symbols and bar.symbol not in self.symbols:
            return

        self._prices[bar.symbol].append(bar.close)
        prices = list(self._prices[bar.symbol])

        if len(prices) < self.long_window:
            return

        short_sma = sum(prices[-self.short_window:]) / self.short_window
        long_sma = sum(prices[-self.long_window:]) / self.long_window

        current_side = self._position_side.get(bar.symbol, "")
        signal: dict[str, Any] | None = None

        if short_sma > long_sma and current_side != "long":
            signal = {
                "symbol": bar.symbol,
                "side": "buy",
                "reason": f"SMA crossover: short={short_sma:.2f} > long={long_sma:.2f}",
            }
            self._position_side[bar.symbol] = "long"

        elif short_sma < long_sma and current_side != "short":
            signal = {
                "symbol": bar.symbol,
                "side": "sell",
                "reason": f"SMA crossover: short={short_sma:.2f} < long={long_sma:.2f}",
            }
            self._position_side[bar.symbol] = "short"

        if signal:
            await self.on_signal(signal)

    async def on_signal(self, signal: Any) -> None:
        """Submit order based on signal."""
        if not self.context:
            return

        side = OrderSide.BUY if signal["side"] == "buy" else OrderSide.SELL
        order = Order(
            symbol=signal["symbol"],
            side=side,
            order_type=OrderType.MARKET,
            quantity=self.quantity,
        )

        await self.event_bus.publish("strategy.signal", {
            "strategy_id": self.name,
            "signal": signal,
        })

        await self.context.submit_order(order)
