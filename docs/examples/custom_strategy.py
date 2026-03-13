"""Custom strategy example — mean reversion with Z-score.

Implements a complete strategy that:
1. Accumulates a rolling window of bar close prices per symbol
2. Computes a Z-score on each new bar
3. Buys when Z < -threshold (price below mean) and sells when Z > threshold

Demonstrates the full Strategy lifecycle: subclassing, configuration,
order submission through StrategyContext, and signal publishing.

Data is provided via the DataManager — either from CSV files, the
ingestion API, or a custom DataProvider. No external data vendor required.

Prerequisites:
    - pip install -e .
    - Prepare CSV data files, or run alongside an external feed script

Usage:
    python docs/examples/custom_strategy.py
"""

from __future__ import annotations

import asyncio
import signal
from collections import defaultdict, deque
from typing import Any

from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.core.models import Bar, Order, QuoteTick, TradeTick
from trading_platform.data import CsvBarProvider, DataConfig, DataManager
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig
from trading_platform.strategy.base import Strategy
from trading_platform.strategy.manager import StrategyManager


# ── Strategy Implementation ────────────────────────────────────────────

class MeanReversionStrategy(Strategy):
    """Buys when price is N std devs below the rolling mean, sells when above."""

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, event_bus, config)
        self.window: int = self.config.get("window", 20)
        self.z_threshold: float = self.config.get("z_threshold", 2.0)
        self.symbols: list[str] = self.config.get("symbols", [])
        self.quantity: float = self.config.get("quantity", 10.0)
        self._prices: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )
        self._log = get_logger(f"strategy.{name}")

    async def on_start(self) -> None:
        self._prices.clear()
        self._log.info("mean reversion started", symbols=self.symbols, window=self.window)

    async def on_stop(self) -> None:
        self._log.info("mean reversion stopped")

    async def on_quote(self, quote: QuoteTick) -> None:
        pass  # This strategy uses bars, not quotes

    async def on_trade(self, trade: TradeTick) -> None:
        pass  # This strategy uses bars, not trades

    async def on_bar(self, bar: Bar) -> None:
        if self.symbols and bar.symbol not in self.symbols:
            return

        self._prices[bar.symbol].append(bar.close)
        prices = list(self._prices[bar.symbol])

        if len(prices) < self.window:
            self._log.debug("buffering", symbol=bar.symbol, count=len(prices))
            return

        mean = sum(prices) / len(prices)
        std = (sum((p - mean) ** 2 for p in prices) / len(prices)) ** 0.5
        if std == 0:
            return
        z_score = (bar.close - mean) / std

        self._log.info(
            "z-score",
            symbol=bar.symbol,
            close=bar.close,
            mean=f"{mean:.2f}",
            std=f"{std:.4f}",
            z=f"{z_score:.2f}",
        )

        if z_score < -self.z_threshold:
            await self._submit(bar.symbol, OrderSide.BUY, f"z={z_score:.2f}")
        elif z_score > self.z_threshold:
            await self._submit(bar.symbol, OrderSide.SELL, f"z={z_score:.2f}")

    async def _submit(self, symbol: str, side: OrderSide, reason: str) -> None:
        await self.event_bus.publish("strategy.signal", {
            "strategy_id": self.name,
            "signal": {"symbol": symbol, "side": str(side), "reason": reason},
        })

        if not self.context:
            self._log.warning("no context — order not submitted")
            return

        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=self.quantity,
        )
        result = await self.context.submit_order(order)
        if result is None:
            self._log.warning("order rejected by risk manager", symbol=symbol)
        else:
            self._log.info("order submitted", symbol=symbol, side=str(side))


# ── Platform Setup ─────────────────────────────────────────────────────

async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.custom_strategy")

    event_bus = EventBus()

    # ── Data: load bars from CSV (or use the ingestion API) ────────────
    # Point csv_directory at your data files, or leave empty and use
    # the REST/WS ingestion endpoints to stream data in from outside.
    data_config = DataConfig(csv_directory="backtest_data", replay_speed=0.0)
    data_manager = DataManager(event_bus, data_config)

    csv_provider = CsvBarProvider("backtest_data", replay_speed=0.0)
    data_manager.register_provider(csv_provider)

    # ── Risk manager with conservative settings ────────────────────────
    risk_config = RiskConfig(
        max_position_size=100.0,
        max_order_value=5000.0,
        daily_loss_limit=-500.0,
        max_open_orders=5,
        max_daily_trades=20,
    )
    risk_manager = RiskManager(risk_config, event_bus)

    # Strategy manager (no exec_adapter means orders are logged but not sent)
    strategy_manager = StrategyManager(
        event_bus=event_bus,
        exec_adapter=None,
        risk_manager=risk_manager,
    )

    # Register and configure the strategy
    symbols = ["AAPL", "MSFT", "TSLA"]
    strategy = MeanReversionStrategy(
        name="mean-reversion-demo",
        event_bus=event_bus,
        config={
            "symbols": symbols,
            "window": 20,
            "z_threshold": 2.0,
            "quantity": 10.0,
        },
    )
    strategy_manager.register(strategy)

    # Start everything
    await strategy_manager.wire_events()
    await strategy_manager.start_strategy("mean-reversion-demo")
    await data_manager.start()
    log.info("strategy running — press Ctrl+C to stop")

    # Wait for shutdown
    shutdown = asyncio.Event()

    def _stop() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    await shutdown.wait()

    # Cleanup
    await data_manager.stop()
    await strategy_manager.stop_all()
    await strategy_manager.unwire_events()
    log.info("shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
