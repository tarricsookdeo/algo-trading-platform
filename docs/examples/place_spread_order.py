"""Place a multi-leg spread order via Public.com.

Demonstrates building and submitting a vertical call spread (bull call
spread) using the PublicComExecAdapter's multileg order support.

Prerequisites:
    - Set PUBLIC_API_SECRET and PUBLIC_ACCOUNT_ID in your .env file
    - pip install -e .

Usage:
    python docs/examples/place_spread_order.py
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from public_api_sdk.models import (
    LegInstrument,
    LegInstrumentType,
    MultilegOrderRequest,
    OpenCloseIndicator,
    OrderExpirationRequest,
    OrderLegRequest,
    OrderSide as SDKOrderSide,
    OrderType as SDKOrderType,
    TimeInForce,
)

from trading_platform.adapters.public_com.adapter import PublicComExecAdapter
from trading_platform.adapters.public_com.config import PublicComConfig
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.spread_order")

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
        # ── Build a bull call spread ───────────────────────────────────
        # Buy 1 AAPL $200 call, sell 1 AAPL $210 call (same expiry)
        long_leg = OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL260320C00200000",
                type=LegInstrumentType.OPTION,
            ),
            order_side=SDKOrderSide.BUY,
            quantity=Decimal("1"),
            open_close_indicator=OpenCloseIndicator.OPEN,
        )

        short_leg = OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL260320C00210000",
                type=LegInstrumentType.OPTION,
            ),
            order_side=SDKOrderSide.SELL,
            quantity=Decimal("1"),
            open_close_indicator=OpenCloseIndicator.OPEN,
        )

        # Net debit spread — set the max debit you're willing to pay
        spread_request = MultilegOrderRequest(
            order_id="spread-example-001",
            order_type=SDKOrderType.LIMIT,
            legs=[long_leg, short_leg],
            limit_price=Decimal("3.50"),  # max net debit
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        )

        log.info(
            "submitting bull call spread",
            long_leg="AAPL260320C00200000",
            short_leg="AAPL260320C00210000",
            max_debit=3.50,
        )

        result = await adapter.submit_multileg_order(spread_request)
        log.info("spread order submitted", result=result)

        # Wait for order tracking
        await asyncio.sleep(5)

    finally:
        await adapter.disconnect()
        log.info("disconnected")


if __name__ == "__main__":
    asyncio.run(main())
