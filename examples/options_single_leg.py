"""Example: Single-leg options order.

Demonstrates buying a call option via the OptionsExecAdapter.
"""

import asyncio
from datetime import date
from decimal import Decimal

from trading_platform.core.events import EventBus
from trading_platform.core.models import Order
from trading_platform.core.enums import (
    OrderSide, OrderType, AssetClass, ContractType,
)
from trading_platform.adapters.options.adapter import OptionsExecAdapter
from trading_platform.adapters.options.config import OptionsConfig


async def main() -> None:
    bus = EventBus()

    config = OptionsConfig(
        api_secret="your_api_secret",
        account_id="your_account_id",
    )
    adapter = OptionsExecAdapter(config, bus)
    await adapter.connect()

    # Buy 1 AAPL call option
    order = Order(
        symbol="AAPL250321C00150000",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=5.00,
        asset_class=AssetClass.OPTION,
        contract_type=ContractType.CALL,
        strike_price=Decimal("150"),
        expiration_date=date(2025, 3, 21),
        underlying_symbol="AAPL",
        option_symbol="AAPL250321C00150000",
    )
    result = await adapter.submit_option_order(order)
    print(f"Option order submitted: {result}")

    # Check options positions
    positions = await adapter.get_option_positions()
    for pos in positions:
        print(f"  {pos.symbol}: {pos.quantity} contracts")

    # Check available expirations
    expirations = await adapter.get_option_expirations("AAPL")
    print(f"Available expirations: {expirations}")

    await adapter.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
