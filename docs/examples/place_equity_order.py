"""Place equity orders via Public.com.

Demonstrates submitting market, limit, and stop orders for equities
through the PublicComExecAdapter. Also shows how to listen for
execution events on the EventBus.

Prerequisites:
    - Set PUBLIC_API_SECRET and PUBLIC_ACCOUNT_ID in your .env file
    - pip install -e .

Usage:
    python docs/examples/place_equity_order.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from trading_platform.adapters.public_com.adapter import PublicComExecAdapter
from trading_platform.adapters.public_com.config import PublicComConfig
from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.core.models import Order


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.equity_order")

    # ── Configure ──────────────────────────────────────────────────────
    config = PublicComConfig(
        api_secret="YOUR_PUBLIC_API_SECRET",
        account_id="YOUR_PUBLIC_ACCOUNT_ID",
    )
    event_bus = EventBus()

    # ── Listen for execution events ────────────────────────────────────
    async def on_execution(channel: str, event: Any) -> None:
        log.info("execution event", channel=channel, event=event)

    for ch in [
        "execution.order.submitted",
        "execution.order.filled",
        "execution.order.cancelled",
        "execution.order.rejected",
        "execution.order.error",
    ]:
        await event_bus.subscribe(ch, on_execution)

    # ── Connect ────────────────────────────────────────────────────────
    adapter = PublicComExecAdapter(config, event_bus)
    await adapter.connect()
    log.info("connected to Public.com")

    try:
        # ── Market order ───────────────────────────────────────────────
        market_order = Order(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        log.info("submitting market order", symbol="AAPL", qty=1.0)
        result = await adapter.submit_order(market_order)
        log.info("market order submitted", order_id=market_order.order_id)

        # ── Limit order ───────────────────────────────────────────────
        limit_order = Order(
            symbol="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=5.0,
            limit_price=400.00,
        )
        log.info("submitting limit order", symbol="MSFT", qty=5.0, price=400.00)
        result = await adapter.submit_order(limit_order)
        log.info("limit order submitted", order_id=limit_order.order_id)

        # ── Stop order ─────────────────────────────────────────────────
        stop_order = Order(
            symbol="TSLA",
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=2.0,
            stop_price=200.00,
        )
        log.info("submitting stop order", symbol="TSLA", qty=2.0, stop=200.00)
        result = await adapter.submit_order(stop_order)
        log.info("stop order submitted", order_id=stop_order.order_id)

        # Give time for order tracking callbacks to fire
        await asyncio.sleep(5)

    finally:
        await adapter.disconnect()
        log.info("disconnected")


if __name__ == "__main__":
    asyncio.run(main())
