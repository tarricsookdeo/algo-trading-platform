"""Portfolio monitor example.

Connects to Public.com, fetches the current portfolio, and prints
positions with quantities and P&L. Also subscribes to portfolio
update events on the EventBus for real-time changes.

Prerequisites:
    - Set PUBLIC_API_SECRET and PUBLIC_ACCOUNT_ID in your .env file
    - pip install -e .

Usage:
    python docs/examples/portfolio_monitor.py
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from trading_platform.adapters.public_com.adapter import PublicComExecAdapter
from trading_platform.adapters.public_com.config import PublicComConfig
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging


def print_positions(positions: list[dict[str, Any]]) -> None:
    """Pretty-print a list of position dicts."""
    if not positions:
        print("  (no positions)")
        return

    print(f"  {'Symbol':<10} {'Qty':>8} {'Avg Price':>12} {'Mkt Value':>12} {'P&L':>12}")
    print(f"  {'-' * 10} {'-' * 8} {'-' * 12} {'-' * 12} {'-' * 12}")
    for p in positions:
        print(
            f"  {p.get('symbol', ''):<10}"
            f" {p.get('quantity', 0):>8.1f}"
            f" ${p.get('avg_entry_price', 0):>10.2f}"
            f" ${p.get('market_value', 0):>10.2f}"
            f" ${p.get('unrealized_pnl', 0):>10.2f}"
        )


def print_account(account: dict[str, Any]) -> None:
    """Pretty-print account info."""
    if not account:
        print("  (no account data)")
        return

    for key, value in account.items():
        if isinstance(value, (int, float)):
            print(f"  {key}: ${value:,.2f}")
        else:
            print(f"  {key}: {value}")


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.portfolio")

    # ── Configure ──────────────────────────────────────────────────────
    config = PublicComConfig(
        api_secret="YOUR_PUBLIC_API_SECRET",
        account_id="YOUR_PUBLIC_ACCOUNT_ID",
        portfolio_refresh=10.0,  # refresh every 10 seconds for demo
    )
    event_bus = EventBus()

    # ── Subscribe to portfolio updates ─────────────────────────────────
    async def on_portfolio_update(channel: str, event: Any) -> None:
        print("\n--- Portfolio Update ---")
        print("Positions:")
        print_positions(event.get("positions", []))
        print("Account:")
        print_account(event.get("account", {}))
        print()

    async def on_account_update(channel: str, event: Any) -> None:
        log.info("account update", event=event)

    await event_bus.subscribe("execution.portfolio.update", on_portfolio_update)
    await event_bus.subscribe("execution.account.update", on_account_update)

    # ── Connect ────────────────────────────────────────────────────────
    adapter = PublicComExecAdapter(config, event_bus)
    await adapter.connect()
    log.info("connected to Public.com")

    # ── Fetch initial snapshot ─────────────────────────────────────────
    await adapter.sync_portfolio()

    positions = await adapter.get_positions()
    account = await adapter.get_account()

    print("\n=== Current Portfolio ===")
    print("Positions:")
    print_positions([p.model_dump(mode="json") for p in positions])
    print("\nAccount:")
    print_account(account)

    # ── Stream updates until Ctrl+C ────────────────────────────────────
    shutdown = asyncio.Event()

    def _stop() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    print("\nMonitoring portfolio updates — press Ctrl+C to stop")
    await shutdown.wait()

    await adapter.disconnect()
    log.info("disconnected")


if __name__ == "__main__":
    asyncio.run(main())
