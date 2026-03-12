"""Place a single-leg option order via Public.com.

Demonstrates placing an option order using the PublicComExecAdapter.
Option symbols follow OCC format: AAPL260320C00200000
(underlying + expiry YYMMDD + C/P + strike * 1000, zero-padded).

Prerequisites:
    - Set PUBLIC_API_SECRET and PUBLIC_ACCOUNT_ID in your .env file
    - pip install -e .

Usage:
    python docs/examples/place_option_order.py
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
    log = get_logger("example.option_order")

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
        "execution.order.rejected",
        "execution.order.error",
    ]:
        await event_bus.subscribe(ch, on_execution)

    # ── Connect ────────────────────────────────────────────────────────
    adapter = PublicComExecAdapter(config, event_bus)
    await adapter.connect()
    log.info("connected to Public.com")

    try:
        # ── Buy a call option ──────────────────────────────────────────
        # OCC symbol: AAPL, expiry 2026-03-20, call, strike $200
        option_symbol = "AAPL260320C00200000"

        order = Order(
            symbol=option_symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,         # 1 contract
            limit_price=5.50,     # premium per share ($5.50 × 100 = $550)
        )
        log.info(
            "submitting option order",
            symbol=option_symbol,
            side="buy",
            qty=1,
            limit_price=5.50,
        )

        # The adapter detects option symbols (length > 10) and sets
        # InstrumentType.OPTION and OpenCloseIndicator.OPEN automatically
        result = await adapter.submit_order(order)
        log.info("option order submitted", order_id=order.order_id)

        # ── Preflight check (optional) ─────────────────────────────────
        # Run a preflight to validate the order before submission
        preflight_order = Order(
            symbol=option_symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            limit_price=5.50,
        )
        preflight_result = await adapter.perform_preflight(preflight_order)
        log.info("preflight result", result=preflight_result)

        # Wait for order tracking
        await asyncio.sleep(5)

    finally:
        await adapter.disconnect()
        log.info("disconnected")


if __name__ == "__main__":
    asyncio.run(main())
