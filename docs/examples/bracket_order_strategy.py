"""Bracket order strategy example — breakout with stop-loss and take-profit.

Demonstrates using synthetic bracket orders within a strategy:
1. Detects breakout above a rolling high
2. Submits a bracket order with entry, stop-loss, and take-profit
3. Listens for bracket lifecycle events

The BracketOrderManager handles the full lifecycle:
- Places the entry order (market or limit)
- After fill, places a resting stop-loss on the exchange
- Monitors bid price and triggers take-profit when target is reached

Prerequisites:
    - pip install -e .
    - Set PUBLIC_API_SECRET and PUBLIC_ACCOUNT_ID in .env (for live execution)
    - Prepare CSV data files or use an external feed script

Usage:
    python docs/examples/bracket_order_strategy.py
"""

from __future__ import annotations

import asyncio
import signal
from collections import defaultdict, deque
from decimal import Decimal
from typing import Any

from trading_platform.bracket.manager import BracketOrderManager
from trading_platform.core.enums import OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.core.models import Bar, QuoteTick, TradeTick
from trading_platform.data import CsvBarProvider, DataConfig, DataManager
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig
from trading_platform.strategy.base import Strategy
from trading_platform.strategy.manager import StrategyManager


class BreakoutBracketStrategy(Strategy):
    """Enters on breakout above rolling high, uses bracket for risk management.

    When price breaks above the N-bar high, submits a bracket order with:
    - Entry: market buy
    - Stop-loss: set at the rolling low (support level)
    - Take-profit: entry + 2x the risk (2:1 reward-to-risk ratio)
    """

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, event_bus, config)
        self.window: int = self.config.get("window", 20)
        self.symbols: list[str] = self.config.get("symbols", [])
        self.quantity: int = self.config.get("quantity", 10)
        self._highs: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.window))
        self._lows: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.window))
        self._active_brackets: dict[str, str] = {}  # symbol → bracket_id
        self._log = get_logger(f"strategy.{name}")

    async def on_start(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._active_brackets.clear()
        self._log.info("breakout bracket strategy started", symbols=self.symbols)

    async def on_stop(self) -> None:
        self._log.info("breakout bracket strategy stopped")

    async def on_quote(self, quote: QuoteTick) -> None:
        pass  # Quotes are consumed by BracketOrderManager for take-profit monitoring

    async def on_trade(self, trade: TradeTick) -> None:
        pass

    async def on_bar(self, bar: Bar) -> None:
        if self.symbols and bar.symbol not in self.symbols:
            return

        self._highs[bar.symbol].append(bar.high)
        self._lows[bar.symbol].append(bar.low)

        if len(self._highs[bar.symbol]) < self.window:
            return

        # Skip if we already have a bracket for this symbol
        if bar.symbol in self._active_brackets:
            return

        rolling_high = max(self._highs[bar.symbol])
        rolling_low = min(self._lows[bar.symbol])

        # Breakout: close above rolling high
        if bar.close > rolling_high:
            risk = Decimal(str(bar.close)) - Decimal(str(rolling_low))
            if risk <= 0:
                return

            stop_loss = Decimal(str(rolling_low))
            take_profit = Decimal(str(bar.close)) + risk * 2  # 2:1 R:R

            self._log.info(
                "breakout detected",
                symbol=bar.symbol,
                close=bar.close,
                rolling_high=rolling_high,
                stop_loss=str(stop_loss),
                take_profit=str(take_profit),
            )

            # Submit bracket order through StrategyContext
            bracket = await self.context.submit_bracket_order(
                symbol=bar.symbol,
                quantity=self.quantity,
                entry_type=OrderType.MARKET,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
            )

            if bracket:
                self._active_brackets[bar.symbol] = bracket.bracket_id
                self._log.info(
                    "bracket order submitted",
                    bracket_id=bracket.bracket_id,
                    symbol=bar.symbol,
                )


# ── Platform Setup ─────────────────────────────────────────────────────

async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.bracket_strategy")

    event_bus = EventBus()

    # ── Data ───────────────────────────────────────────────────────────
    data_config = DataConfig(csv_directory="backtest_data", replay_speed=0.0)
    data_manager = DataManager(event_bus, data_config)
    csv_provider = CsvBarProvider("backtest_data", replay_speed=0.0)
    data_manager.register_provider(csv_provider)

    # ── Risk ───────────────────────────────────────────────────────────
    risk_config = RiskConfig(
        max_position_size=100.0,
        max_order_value=10000.0,
        daily_loss_limit=-1000.0,
        max_open_orders=10,
        max_daily_trades=50,
    )
    risk_manager = RiskManager(risk_config, event_bus)

    # ── Bracket manager (no exec_adapter = orders logged but not sent)
    bracket_manager = BracketOrderManager(event_bus=event_bus, exec_adapter=None)

    # ── Strategy manager ───────────────────────────────────────────────
    strategy_manager = StrategyManager(
        event_bus=event_bus,
        exec_adapter=None,
        risk_manager=risk_manager,
        bracket_manager=bracket_manager,
    )

    # ── Listen for bracket events ──────────────────────────────────────
    async def on_bracket_event(channel: str, event: Any) -> None:
        log.info("bracket event", channel=channel, event=event)

    for ch in [
        "bracket.entry.filled",
        "bracket.stop.placed",
        "bracket.stopped_out",
        "bracket.take_profit.triggered",
        "bracket.take_profit.filled",
        "bracket.canceled",
        "bracket.error",
        "bracket.state_change",
    ]:
        await event_bus.subscribe(ch, on_bracket_event)

    # ── Register strategy ──────────────────────────────────────────────
    strategy = BreakoutBracketStrategy(
        name="breakout-bracket-demo",
        event_bus=event_bus,
        config={
            "symbols": ["AAPL", "MSFT", "TSLA"],
            "window": 20,
            "quantity": 10,
        },
    )
    strategy_manager.register(strategy)

    # ── Start ──────────────────────────────────────────────────────────
    await bracket_manager.wire_events()
    await strategy_manager.wire_events()
    await strategy_manager.start_strategy("breakout-bracket-demo")
    await data_manager.start()
    log.info("bracket strategy running — press Ctrl+C to stop")

    shutdown = asyncio.Event()

    def _stop() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    await shutdown.wait()

    # ── Cleanup ────────────────────────────────────────────────────────
    await data_manager.stop()
    await strategy_manager.stop_all()
    await strategy_manager.unwire_events()
    await bracket_manager.unwire_events()
    log.info("shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
