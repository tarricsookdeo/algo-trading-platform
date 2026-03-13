"""Event listener example.

Subscribes to various EventBus channels and logs all events to the
console. Useful for debugging, monitoring, and understanding the
platform's event flow.

This example shows three subscription patterns:
1. Single-channel subscription (quotes only)
2. Multi-channel subscription (all execution events)
3. Wildcard subscription (every event on every channel)

Data flows in via the DataManager — either from CSV files or through
the REST/WebSocket ingestion endpoints from an external feed.

Prerequisites:
    - pip install -e .

Usage:
    python docs/examples/event_listener.py
"""

from __future__ import annotations

import asyncio
import json
import random
import signal
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.core.models import Bar, QuoteTick, TradeTick
from trading_platform.data import DataConfig, DataManager, DataProvider


class SimulatedFeedProvider(DataProvider):
    """Generates random bars, quotes, and trades for demonstration."""

    def __init__(self, symbols: list[str], interval: float = 1.0) -> None:
        self._symbols = symbols
        self._interval = interval
        self._connected = False
        self._prices: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "simulated-feed"

    async def connect(self) -> None:
        self._prices = {s: 100.0 + random.random() * 200 for s in self._symbols}
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
                change = random.uniform(-1.0, 1.0)
                yield Bar(
                    symbol=symbol,
                    open=round(price, 2),
                    high=round(price + abs(change) + 0.2, 2),
                    low=round(price - abs(change) - 0.2, 2),
                    close=round(price + change, 2),
                    volume=float(random.randint(1000, 50000)),
                    timestamp=datetime.now(timezone.utc),
                )
                self._prices[symbol] = price + change
            await asyncio.sleep(self._interval)

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[QuoteTick]:
        while self._connected:
            for symbol in self._symbols:
                price = self._prices.get(symbol, 150.0)
                spread = random.uniform(0.01, 0.05)
                yield QuoteTick(
                    symbol=symbol,
                    bid_price=round(price, 2),
                    bid_size=float(random.randint(1, 50) * 100),
                    ask_price=round(price + spread, 2),
                    ask_size=float(random.randint(1, 50) * 100),
                    timestamp=datetime.now(timezone.utc),
                )
            await asyncio.sleep(self._interval * 0.5)

    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[TradeTick]:
        while self._connected:
            symbol = random.choice(self._symbols)
            price = self._prices.get(symbol, 150.0)
            yield TradeTick(
                symbol=symbol,
                price=round(price + random.uniform(-0.1, 0.1), 2),
                size=float(random.randint(1, 500)),
                timestamp=datetime.now(timezone.utc),
            )
            await asyncio.sleep(self._interval * 0.3)


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.events")

    event_bus = EventBus()

    # ── Pattern 1: Single-channel subscription ─────────────────────────
    quote_count = 0

    async def on_quote(channel: str, event: Any) -> None:
        nonlocal quote_count
        quote_count += 1
        if quote_count <= 5:
            if isinstance(event, dict):
                print(f"[QUOTE] {event.get('symbol')}: bid={event.get('bid_price')} ask={event.get('ask_price')}")
            else:
                print(f"[QUOTE] {event.symbol}: bid={event.bid_price} ask={event.ask_price}")
        elif quote_count == 6:
            print("[QUOTE] ... (suppressing further quote output)")

    await event_bus.subscribe(Channel.QUOTE, on_quote)

    # ── Pattern 2: Multi-channel subscription ──────────────────────────
    async def on_trade(channel: str, event: Any) -> None:
        if isinstance(event, dict):
            print(f"[TRADE] {event.get('symbol')}: price={event.get('price')} size={event.get('size')}")
        else:
            print(f"[TRADE] {event.symbol}: price={event.price} size={event.size}")

    async def on_bar(channel: str, event: Any) -> None:
        if isinstance(event, dict):
            print(f"[BAR] {event.get('symbol')}: O={event.get('open')} H={event.get('high')} L={event.get('low')} C={event.get('close')} V={event.get('volume')}")
        else:
            print(f"[BAR] {event.symbol}: O={event.open} H={event.high} L={event.low} C={event.close} V={event.volume}")

    async def on_system(channel: str, event: Any) -> None:
        if isinstance(event, dict):
            print(f"[SYSTEM] {event.get('component', '?')}: {event.get('message', '')}")
        else:
            print(f"[SYSTEM] {event}")

    await event_bus.subscribe(Channel.TRADE, on_trade)
    await event_bus.subscribe(Channel.BAR, on_bar)
    await event_bus.subscribe(Channel.SYSTEM, on_system)

    # ── Pattern 3: Wildcard (catch-all) subscription ───────────────────
    # Uncomment the following to see EVERY event on EVERY channel:
    #
    # async def on_any(channel: str, event: Any) -> None:
    #     payload = event
    #     if hasattr(event, "model_dump"):
    #         payload = event.model_dump(mode="json")
    #     print(f"[*] [{channel}] {json.dumps(payload, default=str)[:200]}")
    #
    # await event_bus.subscribe("*", on_any)

    # ── Periodic metrics reporter ──────────────────────────────────────
    async def report_metrics() -> None:
        while True:
            await asyncio.sleep(10)
            rate = event_bus.events_per_second()
            total = event_bus.total_published
            subs = event_bus.subscriber_count
            print(f"\n--- Metrics: {rate:.1f} events/sec | {total} total | {subs} subscribers ---\n")

    metrics_task = asyncio.create_task(report_metrics())

    # ── Start data feed ────────────────────────────────────────────────
    symbols = ["AAPL", "MSFT"]
    config = DataConfig()
    data_manager = DataManager(event_bus, config)

    provider = SimulatedFeedProvider(symbols, interval=2.0)
    data_manager.register_provider(provider)

    await data_manager.start()
    log.info("listening to events", symbols=symbols)

    # ── Run until Ctrl+C ───────────────────────────────────────────────
    shutdown = asyncio.Event()

    def _stop() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    print("Listening for events — press Ctrl+C to stop\n")
    await shutdown.wait()

    metrics_task.cancel()
    await data_manager.stop()

    # Final summary
    print(f"\nFinal summary:")
    print(f"  Total events: {event_bus.total_published}")
    print(f"  Quotes received: {quote_count}")
    for ch, count in sorted(event_bus.channel_counts.items()):
        print(f"  {ch}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
