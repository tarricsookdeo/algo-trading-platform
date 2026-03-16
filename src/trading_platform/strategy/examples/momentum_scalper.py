"""Momentum scalper strategy for TQQQ and SOXL.

Watches real-time quotes and 1-minute bars for short-term long momentum.

Entry conditions (all must be true):
  1. No open bracket already exists for this symbol.
  2. Cooldown period since last entry has elapsed.
  3. Bid/ask spread is within the configured maximum.
  4. Bid price has risen on each of the last N consecutive quote updates.
  5. Most recent 1-minute bar is bullish and closed in the upper half of its range.

On entry: places a market-buy bracket order with:
  - Take profit: entry ask + $0.05
  - Stop loss:   entry ask - $1.00
"""

from __future__ import annotations

import time
from collections import deque
from decimal import Decimal
from typing import Any

from trading_platform.bracket.enums import BracketChannel
from trading_platform.core.enums import OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Bar, QuoteTick, TradeTick
from trading_platform.strategy.base import Strategy


class MomentumScalperStrategy(Strategy):
    """Short-term momentum scalper for TQQQ and SOXL.

    Config:
        symbols: list[str]       — symbols to trade (default: ["TQQQ", "SOXL"])
        quantity: int            — shares per bracket (default: 100)
        take_profit: float       — take-profit offset above ask in dollars (default: 0.05)
        stop_loss: float         — stop-loss offset below ask in dollars (default: 1.00)
        momentum_window: int     — consecutive bid increases required (default: 3)
        max_spread: float        — max bid/ask spread allowed for entry (default: 0.10)
        cooldown_seconds: float  — minimum seconds between entries per symbol (default: 60)
    """

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, event_bus, config)
        self.symbols: list[str] = self.config.get("symbols", ["TQQQ", "SOXL"])
        self.quantity = Decimal(str(self.config.get("quantity", 10)))
        self.take_profit_offset = Decimal(str(self.config.get("take_profit", "0.05")))
        self.stop_loss_offset = Decimal(str(self.config.get("stop_loss", "1.00")))
        self.momentum_window: int = int(self.config.get("momentum_window", 3))
        self.max_spread = Decimal(str(self.config.get("max_spread", "0.10")))
        self.cooldown_seconds: float = float(self.config.get("cooldown_seconds", 60))

        # Per-symbol bid history — holds momentum_window + 1 values so we can
        # compare each consecutive pair.
        self._bid_history: dict[str, deque[Decimal]] = {
            s: deque(maxlen=self.momentum_window + 1) for s in self.symbols
        }
        # Most recent completed bar per symbol
        self._last_bar: dict[str, Bar] = {}
        # Monotonic timestamp of the last entry per symbol
        self._last_entry_time: dict[str, float] = {}
        # bracket_id → symbol for all currently open brackets
        self._open_brackets: dict[str, str] = {}

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def on_start(self) -> None:
        for sym in self.symbols:
            self._bid_history[sym] = deque(maxlen=self.momentum_window + 1)
        self._last_bar.clear()
        self._last_entry_time.clear()
        self._open_brackets.clear()

        # Subscribe directly to bracket completion events so we release the
        # symbol slot as soon as the trade is resolved.
        await self.event_bus.subscribe(BracketChannel.BRACKET_TAKE_PROFIT_FILLED, self._on_bracket_closed)
        await self.event_bus.subscribe(BracketChannel.BRACKET_STOPPED_OUT, self._on_bracket_closed)
        await self.event_bus.subscribe(BracketChannel.BRACKET_CANCELED, self._on_bracket_closed)
        await self.event_bus.subscribe(BracketChannel.BRACKET_ERROR, self._on_bracket_closed)

    async def on_stop(self) -> None:
        self._open_brackets.clear()
        await self.event_bus.unsubscribe(BracketChannel.BRACKET_TAKE_PROFIT_FILLED, self._on_bracket_closed)
        await self.event_bus.unsubscribe(BracketChannel.BRACKET_STOPPED_OUT, self._on_bracket_closed)
        await self.event_bus.unsubscribe(BracketChannel.BRACKET_CANCELED, self._on_bracket_closed)
        await self.event_bus.unsubscribe(BracketChannel.BRACKET_ERROR, self._on_bracket_closed)

    # ── Market data ─────────────────────────────────────────────────────

    async def on_quote(self, quote: QuoteTick) -> None:
        if quote.symbol not in self.symbols:
            return

        sym = quote.symbol
        bid = Decimal(str(quote.bid_price))
        ask = Decimal(str(quote.ask_price))

        self._bid_history[sym].append(bid)

        # Wait until the history is full and we have at least one confirmed bar.
        if len(self._bid_history[sym]) < self.momentum_window + 1:
            return
        if sym not in self._last_bar:
            return

        await self._evaluate(sym, bid, ask)

    async def on_trade(self, trade: TradeTick) -> None:
        pass  # not used by this strategy

    async def on_bar(self, bar: Bar) -> None:
        if bar.symbol in self.symbols:
            self._last_bar[bar.symbol] = bar

    # ── Entry evaluation ────────────────────────────────────────────────

    async def _evaluate(self, symbol: str, bid: Decimal, ask: Decimal) -> None:
        """Check all entry conditions and submit a bracket if they are all met."""
        if not self.context:
            return

        # 1. No open bracket for this symbol
        if symbol in self._open_brackets.values():
            return

        # 2. Cooldown
        elapsed = time.monotonic() - self._last_entry_time.get(symbol, 0.0)
        if elapsed < self.cooldown_seconds:
            return

        # 3. Spread filter — wide spreads mean poor fill quality
        if (ask - bid) > self.max_spread:
            return

        # 4. Consecutive bid momentum — every bid must be strictly higher than
        #    the one before it across the full momentum window.
        bids = list(self._bid_history[symbol])
        if not all(bids[i] > bids[i - 1] for i in range(1, len(bids))):
            return

        # 5. Bullish bar confirmation — bar must be green and close in the upper
        #    half of its range (filters out wicks and indecisive candles).
        bar = self._last_bar[symbol]
        bar_range = Decimal(str(bar.high)) - Decimal(str(bar.low))
        if bar_range <= 0 or bar.close <= bar.open:
            return
        close_position = (Decimal(str(bar.close)) - Decimal(str(bar.low))) / bar_range
        if close_position < Decimal("0.5"):
            return

        await self._enter(symbol, ask)

    async def _enter(self, symbol: str, ask: Decimal) -> None:
        """Place a market-entry bracket order."""
        tp = ask + self.take_profit_offset
        sl = ask - self.stop_loss_offset

        try:
            bracket = await self.context.submit_bracket_order(
                symbol=symbol,
                quantity=self.quantity,
                entry_type=OrderType.MARKET,
                stop_loss_price=sl,
                take_profit_price=tp,
            )
        except Exception as exc:
            await self.event_bus.publish("strategy.error", {
                "strategy_id": self.name,
                "symbol": symbol,
                "error": str(exc),
            })
            return

        if bracket:
            self._open_brackets[bracket.bracket_id] = symbol
            self._last_entry_time[symbol] = time.monotonic()
            await self.event_bus.publish("strategy.signal", {
                "strategy_id": self.name,
                "symbol": symbol,
                "action": "long_entry",
                "ask": str(ask),
                "take_profit": str(tp),
                "stop_loss": str(sl),
                "quantity": str(self.quantity),
                "bracket_id": bracket.bracket_id,
            })

    # ── Bracket completion ──────────────────────────────────────────────

    async def _on_bracket_closed(self, channel: str, event: Any) -> None:
        """Free the symbol slot when a bracket resolves in any terminal state."""
        bracket_id = event.get("bracket_id") if isinstance(event, dict) else None
        if bracket_id:
            self._open_brackets.pop(bracket_id, None)
