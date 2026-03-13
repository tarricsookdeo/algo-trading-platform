"""Custom DataProvider example — random data generator.

Implements the DataProvider ABC to generate random price data for
testing. Demonstrates the full provider lifecycle: connect, stream,
disconnect.

Prerequisites:
    - pip install -e .

Usage:
    python docs/examples/custom_provider.py
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
from trading_platform.core.models import Bar, QuoteTick, TradeTick
from trading_platform.data.manager import DataManager
from trading_platform.data.provider import DataProvider


class RandomDataProvider(DataProvider):
    """Generates random price data for testing.

    Produces synthetic bar, quote, and trade data at configurable
    intervals. Useful for testing strategies without real market data.
    """

    def __init__(
        self,
        symbols: list[str],
        bar_interval: float = 1.0,
        quote_interval: float = 0.5,
        trade_interval: float = 0.2,
    ) -> None:
        self._symbols = symbols
        self._bar_interval = bar_interval
        self._quote_interval = quote_interval
        self._trade_interval = trade_interval
        self._connected = False
        self._prices: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "random-data"

    async def connect(self) -> None:
        # Initialize base prices for each symbol
        self._prices = {s: random.uniform(100, 500) for s in self._symbols}
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        while self._connected:
            for symbol in self._symbols:
                price = self._prices[symbol]
                change = random.gauss(0, price * 0.001)
                open_price = price
                close_price = price + change
                high = max(open_price, close_price) + abs(random.gauss(0, price * 0.0005))
                low = min(open_price, close_price) - abs(random.gauss(0, price * 0.0005))

                bar = Bar(
                    symbol=symbol,
                    open=round(open_price, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close_price, 2),
                    volume=float(random.randint(1000, 50000)),
                    timestamp=datetime.now(timezone.utc),
                )
                self._prices[symbol] = close_price
                yield bar

            await asyncio.sleep(self._bar_interval)

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[QuoteTick]:
        while self._connected:
            for symbol in self._symbols:
                price = self._prices.get(symbol, 100.0)
                spread = random.uniform(0.01, 0.10)
                quote = QuoteTick(
                    symbol=symbol,
                    bid_price=round(price - spread / 2, 2),
                    bid_size=float(random.randint(1, 100)),
                    ask_price=round(price + spread / 2, 2),
                    ask_size=float(random.randint(1, 100)),
                    timestamp=datetime.now(timezone.utc),
                )
                yield quote

            await asyncio.sleep(self._quote_interval)

    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[TradeTick]:
        while self._connected:
            symbol = random.choice(self._symbols)
            price = self._prices.get(symbol, 100.0)
            noise = random.gauss(0, price * 0.0002)
            trade = TradeTick(
                symbol=symbol,
                price=round(price + noise, 2),
                size=float(random.randint(1, 500)),
                timestamp=datetime.now(timezone.utc),
            )
            yield trade

            await asyncio.sleep(self._trade_interval)


# ── Run the provider with DataManager ──────────────────────────────────

async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.custom_provider")

    event_bus = EventBus()
    data_manager = DataManager(event_bus)

    # Register our custom provider
    provider = RandomDataProvider(
        symbols=["AAPL", "MSFT", "TSLA"],
        bar_interval=2.0,
        quote_interval=1.0,
        trade_interval=0.5,
    )
    data_manager.register_provider(provider)

    # Subscribe to events for display
    bar_count = 0

    async def on_bar(channel: str, event: dict) -> None:
        nonlocal bar_count
        bar_count += 1
        if bar_count <= 10:
            print(f"[BAR] {event.get('symbol')}: "
                  f"O={event.get('open')} H={event.get('high')} "
                  f"L={event.get('low')} C={event.get('close')} "
                  f"V={event.get('volume')}")

    async def on_quote(channel: str, event: dict) -> None:
        print(f"[QUOTE] {event.get('symbol')}: "
              f"bid={event.get('bid_price')} ask={event.get('ask_price')}")

    await event_bus.subscribe(Channel.BAR, on_bar)
    await event_bus.subscribe(Channel.QUOTE, on_quote)

    # Start streaming
    await data_manager.start()
    log.info("random data provider running — press Ctrl+C to stop")

    # Wait for shutdown
    shutdown = asyncio.Event()

    def _stop() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    await shutdown.wait()

    await data_manager.stop()
    stats = data_manager.get_ingestion_stats()
    print(f"\nFinal ingestion stats: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
