"""Example: Scaled exit (multi-tranche take-profit).

Demonstrates selling a position in 3 tranches at different price levels.

NOTE: In production, pass a real exec_adapter to ScaledOrderManager.
The create_scaled_exit/entry methods require an adapter to place orders.
This script shows the API shape and event wiring pattern.
"""

import asyncio
from decimal import Decimal

from trading_platform.core.events import EventBus
from trading_platform.orders.scaled import ScaledOrderManager


async def main() -> None:
    bus = EventBus()

    # In production, pass a real exec_adapter.
    # create_scaled_exit() requires an adapter to place the stop-loss order.
    som = ScaledOrderManager(bus, exec_adapter=None)
    await som.wire_events()

    # Listen for scaled order events
    async def on_scaled(channel: str, event: object) -> None:
        print(f"[{channel}] {event}")

    await bus.subscribe("scaled.exit.placed", on_scaled)
    await bus.subscribe("scaled.exit.tranche_filled", on_scaled)
    await bus.subscribe("scaled.exit.completed", on_scaled)

    # --- Scaled exit: sell 100 shares in 3 tranches ---
    # take_profit_levels is a list of (price, quantity_fraction) tuples.
    # The fractions must sum to Decimal("1").
    #
    # In production with a real adapter:
    #
    #   exit_order = await som.create_scaled_exit(
    #       symbol="AAPL",
    #       total_quantity=Decimal("100"),
    #       take_profit_levels=[
    #           (Decimal("155.00"), Decimal("0.50")),   # 50% at $155
    #           (Decimal("160.00"), Decimal("0.30")),   # 30% at $160
    #           (Decimal("165.00"), Decimal("0.20")),   # 20% at $165
    #       ],
    #       stop_loss_price=Decimal("145.00"),
    #   )
    #   print(f"Scaled exit created: {exit_order.scaled_id}")
    #   print(f"  Total quantity: {exit_order.total_quantity}")
    #   print(f"  Stop loss: ${exit_order.stop_loss_price}")
    #   print(f"  Tranches:")
    #   for i, t in enumerate(exit_order.tranches):
    #       print(f"    [{i}] ${t.price} x {t.quantity} (filled={t.filled})")

    # --- Scaled entry: buy 100 shares in 3 tranches ---
    #
    #   entry_order = await som.create_scaled_entry(
    #       symbol="MSFT",
    #       total_quantity=Decimal("100"),
    #       entry_levels=[
    #           (Decimal("400.00"), Decimal("0.50")),   # 50% at $400
    #           (Decimal("395.00"), Decimal("0.30")),   # 30% at $395
    #           (Decimal("390.00"), Decimal("0.20")),   # 20% at $390
    #       ],
    #       stop_loss_price=Decimal("385.00"),
    #   )
    #   print(f"Scaled entry created: {entry_order.scaled_id}")
    #   print(f"  Total quantity: {entry_order.total_quantity}")

    await som.unwire_events()


if __name__ == "__main__":
    asyncio.run(main())
