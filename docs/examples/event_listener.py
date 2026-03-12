"""Event listener example.

Subscribes to various EventBus channels and logs all events to the
console. Useful for debugging, monitoring, and understanding the
platform's event flow.

This example shows three subscription patterns:
1. Single-channel subscription (quotes only)
2. Multi-channel subscription (all execution events)
3. Wildcard subscription (every event on every channel)

Prerequisites:
    - Set ALPACA_API_KEY and ALPACA_API_SECRET in your .env file
    - pip install -e .

Usage:
    python docs/examples/event_listener.py
"""

from __future__ import annotations

import asyncio
import json
import signal
from typing import Any

from trading_platform.adapters.alpaca.adapter import AlpacaDataAdapter
from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.events")

    event_bus = EventBus()

    # ── Pattern 1: Single-channel subscription ─────────────────────────
    quote_count = 0

    async def on_quote(channel: str, event: Any) -> None:
        nonlocal quote_count
        quote_count += 1
        if quote_count <= 5:  # Only print first 5 quotes
            print(f"[QUOTE] {event.symbol}: bid={event.bid_price} ask={event.ask_price}")
        elif quote_count == 6:
            print("[QUOTE] ... (suppressing further quote output)")

    await event_bus.subscribe(Channel.QUOTE, on_quote)

    # ── Pattern 2: Multi-channel subscription ──────────────────────────
    async def on_trade(channel: str, event: Any) -> None:
        print(f"[TRADE] {event.symbol}: price={event.price} size={event.size}")

    async def on_bar(channel: str, event: Any) -> None:
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

    # ── Connect and subscribe to market data ───────────────────────────
    alpaca_config = AlpacaConfig(
        api_key="YOUR_ALPACA_API_KEY",
        api_secret="YOUR_ALPACA_API_SECRET",
        feed="sip",
    )
    adapter = AlpacaDataAdapter(alpaca_config, event_bus)

    symbols = ["AAPL", "MSFT"]
    await adapter.connect()
    await adapter.subscribe_quotes(symbols)
    await adapter.subscribe_trades(symbols)
    await adapter.subscribe_bars(symbols)
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
    await adapter.disconnect()

    # Final summary
    print(f"\nFinal summary:")
    print(f"  Total events: {event_bus.total_published}")
    print(f"  Quotes received: {quote_count}")
    for ch, count in sorted(event_bus.channel_counts.items()):
        print(f"  {ch}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
