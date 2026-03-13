"""Example: Iron condor strategy via OptionsStrategyBuilder.

Builds and validates a 4-leg iron condor, then submits via OrderRouter.
"""

import asyncio
from datetime import date
from decimal import Decimal

from trading_platform.core.events import EventBus
from trading_platform.core.enums import AssetClass
from trading_platform.core.order_router import OrderRouter
from trading_platform.options.strategy_builder import OptionsStrategyBuilder
from trading_platform.options.strategies import IronCondorParams
from trading_platform.options.validator import StrategyValidator
from trading_platform.adapters.options.adapter import OptionsExecAdapter
from trading_platform.adapters.options.config import OptionsConfig


async def main() -> None:
    bus = EventBus()

    # Set up options adapter and router
    config = OptionsConfig(api_secret="secret", account_id="acct")
    adapter = OptionsExecAdapter(config, bus)
    await adapter.connect()

    router = OrderRouter()
    router.register(AssetClass.OPTION, adapter)

    # Define iron condor parameters
    params = IronCondorParams(
        underlying="SPY",
        expiration=date(2025, 4, 18),
        put_long_strike=Decimal("440"),
        put_short_strike=Decimal("445"),
        call_short_strike=Decimal("460"),
        call_long_strike=Decimal("465"),
        quantity=Decimal("2"),
    )

    # Validate first
    validator = StrategyValidator()
    analysis = validator.validate_iron_condor(params)
    print(f"Valid: {analysis.is_valid}")
    print(f"Max profit: {analysis.max_profit}")
    print(f"Max loss: {analysis.max_loss}")
    print(f"Breakevens: {analysis.breakevens}")

    if not analysis.is_valid:
        print(f"Validation errors: {analysis.errors}")
        return

    # Build and submit
    builder = OptionsStrategyBuilder()
    order = await builder.build_and_submit(params, router)
    print(f"Iron condor submitted: {order.id}, legs={len(order.legs)}")

    await adapter.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
