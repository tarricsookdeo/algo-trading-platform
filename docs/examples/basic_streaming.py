"""Basic streaming example.

Connects to Alpaca's SIP market data stream, subscribes to real-time
quotes for a handful of symbols, and prints each update to the console.

Prerequisites:
    - Set ALPACA_API_KEY and ALPACA_API_SECRET in your .env file
    - pip install -e .

Usage:
    python docs/examples/basic_streaming.py
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone

from trading_platform.adapters.alpaca.adapter import AlpacaDataAdapter
from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.core.models import QuoteTick


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.streaming")

    # ── Configure ──────────────────────────────────────────────────────
    # Replace with your Alpaca credentials, or load from .env / config.toml
    config = AlpacaConfig(
        api_key="YOUR_ALPACA_API_KEY",
        api_secret="YOUR_ALPACA_API_SECRET",
        feed="sip",  # "sip" for full market data, "iex" for free tier
    )

    symbols = ["AAPL", "MSFT", "TSLA"]
    event_bus = EventBus()

    # ── Quote handler ──────────────────────────────────────────────────
    async def on_quote(channel: str, event: QuoteTick) -> None:
        spread = event.ask_price - event.bid_price
        log.info(
            "quote",
            symbol=event.symbol,
            bid=event.bid_price,
            ask=event.ask_price,
            spread=f"{spread:.4f}",
            bid_size=event.bid_size,
            ask_size=event.ask_size,
        )

    await event_bus.subscribe(Channel.QUOTE, on_quote)

    # ── Connect and subscribe ──────────────────────────────────────────
    adapter = AlpacaDataAdapter(config, event_bus)
    await adapter.connect()
    await adapter.subscribe_quotes(symbols)
    log.info("subscribed to quotes", symbols=symbols)

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
    await adapter.disconnect()

    # Print summary
    print(f"\nTotal events received: {event_bus.total_published}")
    for ch, count in sorted(event_bus.channel_counts.items()):
        print(f"  {ch}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
