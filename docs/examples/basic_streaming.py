"""Basic streaming example.

Demonstrates how to stream data into the platform using the DataManager
and a custom DataProvider. Uses a simple simulated data provider that
generates random quote ticks for a list of symbols.

Prerequisites:
    - pip install -e .

Usage:
    python docs/examples/basic_streaming.py
"""

from __future__ import annotations

import asyncio
import random
import signal
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.core.models import QuoteTick
from trading_platform.data import DataConfig, DataManager, DataProvider


class SimulatedQuoteProvider(DataProvider):
    """Generates random quote ticks for demonstration."""

    def __init__(self, symbols: list[str], interval: float = 0.5) -> None:
        self._symbols = symbols
        self._interval = interval
        self._connected = False
        self._prices: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "simulated-quotes"

    async def connect(self) -> None:
        self._prices = {s: 100.0 + random.random() * 200 for s in self._symbols}
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[QuoteTick]:
        while self._connected:
            for symbol in self._symbols:
                price = self._prices[symbol]
                price += random.uniform(-0.50, 0.50)
                self._prices[symbol] = price
                spread = random.uniform(0.01, 0.05)
                yield QuoteTick(
                    symbol=symbol,
                    bid_price=round(price, 2),
                    bid_size=float(random.randint(1, 50) * 100),
                    ask_price=round(price + spread, 2),
                    ask_size=float(random.randint(1, 50) * 100),
                    timestamp=datetime.now(timezone.utc),
                )
            await asyncio.sleep(self._interval)


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.streaming")

    symbols = ["AAPL", "MSFT", "TSLA"]
    event_bus = EventBus()

    # ── Quote handler ──────────────────────────────────────────────────
    async def on_quote(channel: str, event: QuoteTick | dict) -> None:
        if isinstance(event, dict):
            sym = event.get("symbol", "?")
            bid = event.get("bid_price", 0)
            ask = event.get("ask_price", 0)
        else:
            sym, bid, ask = event.symbol, event.bid_price, event.ask_price
        spread = ask - bid
        log.info("quote", symbol=sym, bid=bid, ask=ask, spread=f"{spread:.4f}")

    await event_bus.subscribe(Channel.QUOTE, on_quote)

    # ── Set up data manager with simulated provider ────────────────────
    config = DataConfig()
    data_manager = DataManager(event_bus, config)

    provider = SimulatedQuoteProvider(symbols, interval=1.0)
    data_manager.register_provider(provider)

    await data_manager.start()
    log.info("streaming quotes", symbols=symbols)

    # ── Run until Ctrl+C ───────────────────────────────────────────────
    shutdown = asyncio.Event()

    def _stop() -> None:
        log.info("shutting down")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    log.info("streaming — press Ctrl+C to stop")
    await shutdown.wait()

    # ── Cleanup ────────────────────────────────────────────────────────
    await data_manager.stop()

    print(f"\nTotal events received: {event_bus.total_published}")
    for ch, count in sorted(event_bus.channel_counts.items()):
        print(f"  {ch}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
