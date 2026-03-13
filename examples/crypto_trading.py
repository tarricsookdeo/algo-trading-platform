"""Example: Crypto trading via Public.com.

Demonstrates fractional quantity crypto orders through the CryptoExecAdapter.
"""

import asyncio
from decimal import Decimal

from trading_platform.core.events import EventBus
from trading_platform.core.models import Order
from trading_platform.core.enums import OrderSide, OrderType, AssetClass
from trading_platform.adapters.crypto.adapter import CryptoExecAdapter
from trading_platform.adapters.crypto.config import CryptoConfig


async def main() -> None:
    bus = EventBus()

    # Configure crypto adapter
    config = CryptoConfig(
        api_secret="your_api_secret",
        account_id="your_account_id",
        trading_pairs=["BTC-USD", "ETH-USD"],
    )
    adapter = CryptoExecAdapter(config, bus)
    await adapter.connect()

    # Subscribe to execution events
    async def on_exec(channel: str, event: object) -> None:
        print(f"[{channel}] {event}")

    await bus.subscribe("execution.order.submitted", on_exec)
    await bus.subscribe("execution.order.filled", on_exec)

    # Market buy 0.005 BTC
    btc_order = Order(
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.005"),
        asset_class=AssetClass.CRYPTO,
    )
    result = await adapter.submit_order(btc_order)
    print(f"BTC order submitted: {result}")

    # Limit buy 1.5 ETH at $3,500
    eth_order = Order(
        symbol="ETH-USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1.5"),
        limit_price=3500.00,
        asset_class=AssetClass.CRYPTO,
    )
    result = await adapter.submit_order(eth_order)
    print(f"ETH order submitted: {result}")

    # Check positions
    positions = await adapter.get_positions()
    for pos in positions:
        print(f"  {pos.symbol}: {pos.quantity} @ ${pos.avg_entry_price}")

    await adapter.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
