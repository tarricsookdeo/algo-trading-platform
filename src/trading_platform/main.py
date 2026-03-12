"""Platform entry point.

Boots the event bus, Alpaca adapter, and dashboard. Handles graceful
shutdown on SIGINT / SIGTERM.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

import uvicorn

from trading_platform.adapters.alpaca.adapter import AlpacaDataAdapter
from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.core.config import load_settings
from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.dashboard.app import create_app
from trading_platform.dashboard.ws import DashboardWSManager

BANNER = r"""
    _    _             _____              _ _
   / \  | | __ _  ___ |_   _| __ __ _  __| (_)_ __   __ _
  / _ \ | |/ _` |/ _ \  | || '__/ _` |/ _` | | '_ \ / _` |
 / ___ \| | (_| | (_) | | || | | (_| | (_| | | | | | (_| |
/_/   \_\_|\__, |\___/  |_||_|  \__,_|\__,_|_|_| |_|\__, |
           |___/                                     |___/
           P L A T F O R M   v0.1.0
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Algo Trading Platform")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to config.toml",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    """Async main loop."""
    # ── Configuration ──────────────────────────────────────────────────
    settings = load_settings(args.config)
    log_level = args.log_level or settings.platform.log_level
    setup_logging(level=log_level)
    log = get_logger("platform.main")

    print(BANNER)
    log.info(
        "starting platform",
        symbols=settings.platform.symbols,
        feed=settings.alpaca.feed,
        dashboard_port=settings.dashboard.port,
    )

    # ── Core ───────────────────────────────────────────────────────────
    event_bus = EventBus()

    # ── Alpaca Adapter ─────────────────────────────────────────────────
    alpaca_config = AlpacaConfig(
        api_key=settings.alpaca.api_key,
        api_secret=settings.alpaca.api_secret,
        feed=settings.alpaca.feed,
        stock_ws_url=settings.alpaca.stock_ws_url,
        options_ws_url=settings.alpaca.options_ws_url,
        rest_base_url=settings.alpaca.base_url,
        trading_base_url=settings.alpaca.trading_base_url,
    )
    adapter = AlpacaDataAdapter(alpaca_config, event_bus)

    # ── Dashboard ──────────────────────────────────────────────────────
    app, ws_manager = create_app(event_bus, adapter=adapter)

    # ── Shutdown handling ──────────────────────────────────────────────
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # ── Start everything ───────────────────────────────────────────────
    try:
        await adapter.connect()

        # Subscribe to configured symbols
        symbols = settings.platform.symbols
        await adapter.subscribe_trades(symbols)
        await adapter.subscribe_quotes(symbols)
        await adapter.subscribe_bars(symbols)
        log.info("subscribed to symbols", symbols=symbols)

        # Start WS manager
        await ws_manager.start()

        # Start uvicorn as a task
        uvi_config = uvicorn.Config(
            app,
            host=settings.dashboard.host,
            port=settings.dashboard.port,
            log_level=log_level.lower(),
            access_log=False,
        )
        server = uvicorn.Server(uvi_config)
        server_task = asyncio.create_task(server.serve())

        await event_bus.publish(
            Channel.SYSTEM,
            {
                "component": "platform",
                "message": f"dashboard running on http://{settings.dashboard.host}:{settings.dashboard.port}",
                "level": "info",
            },
        )
        log.info(
            "platform ready",
            dashboard=f"http://{settings.dashboard.host}:{settings.dashboard.port}",
        )

        # Wait for shutdown signal
        await shutdown_event.wait()

    finally:
        log.info("shutting down platform")
        await ws_manager.stop()
        await adapter.disconnect()
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        log.info("platform stopped")


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
