"""Example: Trailing stop order.

Demonstrates creating a trailing stop that ratchets up as price rises.

NOTE: In production, pass a real exec_adapter to TrailingStopManager.
The create_trailing_stop method requires an adapter to place the initial
stop order.  This script shows the API shape and event wiring pattern.
"""

import asyncio
from decimal import Decimal

from trading_platform.core.events import EventBus
from trading_platform.orders.trailing_stop import TrailingStopManager


async def main() -> None:
    bus = EventBus()

    # In production, pass a real exec_adapter.
    # create_trailing_stop() requires an adapter to place the stop order.
    tsm = TrailingStopManager(bus, exec_adapter=None)
    await tsm.wire_events()

    # Listen for trailing stop events
    async def on_ts(channel: str, event: object) -> None:
        print(f"[{channel}] {event}")

    await bus.subscribe("trailing_stop.placed", on_ts)
    await bus.subscribe("trailing_stop.updated", on_ts)
    await bus.subscribe("trailing_stop.completed", on_ts)

    # --- Example 1: Trailing stop with absolute dollar trail ---
    # In production with a real adapter:
    #
    #   ts = await tsm.create_trailing_stop(
    #       symbol="AAPL",
    #       quantity=Decimal("100"),
    #       current_price=Decimal("155.00"),
    #       trail_amount=Decimal("2.00"),
    #   )
    #   print(f"Trailing stop created: {ts.trailing_stop_id}")
    #   print(f"  Stop price: ${ts.current_stop_price}")
    #   print(f"  Highest price: ${ts.highest_price}")
    #   print(f"  State: {ts.state}")

    # --- Example 2: Trailing stop with percentage trail ---
    # trail_percent is expressed as a fraction between 0 and 1 (e.g., 0.015 for 1.5%)
    #
    #   ts2 = await tsm.create_trailing_stop(
    #       symbol="MSFT",
    #       quantity=Decimal("50"),
    #       current_price=Decimal("400.00"),
    #       trail_percent=Decimal("0.015"),  # 1.5% trail
    #   )
    #   print(f"Trailing stop created: {ts2.trailing_stop_id}")
    #   print(f"  Stop price: ${ts2.current_stop_price}")

    # Query active trailing stops
    active = tsm.get_active_trailing_stops()
    print(f"Active trailing stops: {len(active)}")

    await tsm.unwire_events()


if __name__ == "__main__":
    asyncio.run(main())
