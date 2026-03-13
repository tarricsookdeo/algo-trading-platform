"""Expiration management example.

Demonstrates how to configure and use the ExpirationManager to monitor
options positions approaching expiration, receive DTE alerts, and
auto-close positions.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from trading_platform.core.enums import ContractType
from trading_platform.core.events import EventBus
from trading_platform.options.expiration import (
    ExpirationConfig,
    ExpirationManager,
    OptionsPosition,
)


async def main() -> None:
    event_bus = EventBus()
    print("=== Expiration Management Example ===\n")

    # --- 1. Configure expiration thresholds ---
    config = ExpirationConfig(
        auto_close_dte=1,              # auto-close at 1 DTE
        alert_dte=7,                   # warn at 7 DTE
        roll_enabled=False,            # disable rolling for this example
        roll_target_dte=30,            # if rolling, target ~30 DTE
        check_interval_seconds=60.0,   # check every 60 seconds
    )
    print(f"Config: alert at {config.alert_dte} DTE, "
          f"auto-close at {config.auto_close_dte} DTE")

    # --- 2. Create the manager ---
    # In production, pass a real exec_adapter for auto-close orders
    # and a strategy_builder for position rolling.
    manager = ExpirationManager(
        config=config,
        event_bus=event_bus,
        exec_adapter=None,
        strategy_builder=None,
    )

    # --- 3. Subscribe to expiration events ---
    async def on_expiration_warning(channel: str, data: object) -> None:
        print(f"  WARNING: {data}")

    async def on_auto_closed(channel: str, data: object) -> None:
        print(f"  AUTO-CLOSED: {data}")

    async def on_rolled(channel: str, data: object) -> None:
        print(f"  ROLLED: {data}")

    await event_bus.subscribe("options.expiration.warning", on_expiration_warning)
    await event_bus.subscribe("options.position.auto_closed", on_auto_closed)
    await event_bus.subscribe("options.position.rolled", on_rolled)

    # --- 4. Set positions to monitor ---
    today = date.today()
    positions = [
        OptionsPosition(
            symbol="AAPL250321C00150000",
            underlying="AAPL",
            quantity=5,
            contract_type=ContractType.CALL,
            strike_price=150.0,
            expiration_date=today + timedelta(days=5),
            strategy_type="",
        ),
        OptionsPosition(
            symbol="MSFT250328P00400000",
            underlying="MSFT",
            quantity=-3,
            contract_type=ContractType.PUT,
            strike_price=400.0,
            expiration_date=today + timedelta(days=15),
            strategy_type="",
        ),
        OptionsPosition(
            symbol="TSLA250314C00250000",
            underlying="TSLA",
            quantity=2,
            contract_type=ContractType.CALL,
            strike_price=250.0,
            expiration_date=today + timedelta(days=1),
            strategy_type="",
        ),
    ]

    manager.set_positions(positions)
    print(f"\nMonitoring {len(positions)} positions:")
    for p in positions:
        dte = (p.expiration_date - today).days
        print(f"  {p.symbol} — {dte} DTE "
              f"({'ALERT ZONE' if dte <= config.alert_dte else 'OK'})")

    # --- 5. Trigger a manual check ---
    print("\nRunning expiration check...")
    await manager.check_expirations(today)

    # Allow events to propagate
    await asyncio.sleep(0.1)

    # --- 6. In production, call start() for periodic checks ---
    # await manager.start()
    # ... run until shutdown ...
    # await manager.stop()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
