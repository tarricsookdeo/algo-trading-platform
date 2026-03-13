"""Example: Vertical spread (bull call) via OptionsStrategyBuilder.

Builds a bull call spread with validation.
"""

import asyncio
from datetime import date
from decimal import Decimal

from trading_platform.core.events import EventBus
from trading_platform.core.enums import AssetClass, ContractType
from trading_platform.core.order_router import OrderRouter
from trading_platform.options.strategy_builder import OptionsStrategyBuilder
from trading_platform.options.strategies import VerticalSpreadParams
from trading_platform.options.validator import StrategyValidator
from trading_platform.adapters.options.adapter import OptionsExecAdapter
from trading_platform.adapters.options.config import OptionsConfig


async def main() -> None:
    bus = EventBus()

    config = OptionsConfig(api_secret="secret", account_id="acct")
    adapter = OptionsExecAdapter(config, bus)
    await adapter.connect()

    router = OrderRouter()
    router.register(AssetClass.OPTION, adapter)

    # Bull call spread: buy lower strike, sell higher strike
    params = VerticalSpreadParams(
        underlying="AAPL",
        expiration=date(2025, 4, 18),
        long_strike=Decimal("150"),
        short_strike=Decimal("160"),
        contract_type=ContractType.CALL,
        quantity=Decimal("5"),
    )

    # Validate
    validator = StrategyValidator()
    analysis = validator.validate_vertical_spread(params)
    print(f"Valid: {analysis.is_valid}")
    if analysis.max_profit:
        print(f"Max profit: ${analysis.max_profit}")
    if analysis.max_loss:
        print(f"Max loss: ${analysis.max_loss}")

    # Build and submit
    builder = OptionsStrategyBuilder()
    order = builder.build_vertical_spread(params)
    print(f"Spread: {order.strategy_type}, legs={len(order.legs)}")

    result = await router.submit_multileg_order(order)
    print(f"Submitted: {result}")

    await adapter.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
