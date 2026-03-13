"""Greeks monitoring example.

Demonstrates how to use the GreeksProvider to fetch option greeks,
aggregate portfolio-level greeks, and monitor them for risk purposes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from trading_platform.core.events import EventBus
from trading_platform.options.greeks import AggregatedGreeks, GreeksData, GreeksProvider


@dataclass
class MockPosition:
    """Minimal position for demonstration."""

    symbol: str
    quantity: float


async def main() -> None:
    event_bus = EventBus()

    # GreeksProvider requires a client with a .raw attribute.
    # In production this is an OptionsClient connected to Public.com.
    # Here we show the API surface without a live connection.
    print("=== Greeks Monitoring Example ===\n")

    # --- 1. Create the provider ---
    # client = OptionsClient(...)  # your real client
    # provider = GreeksProvider(client, refresh_interval=30.0)
    # For demo purposes we illustrate the dataclasses directly.

    # --- 2. Single-option greeks ---
    sample_greeks = GreeksData(
        delta=0.55,
        gamma=0.04,
        theta=-0.12,
        vega=0.28,
        rho=0.03,
        implied_volatility=0.32,
    )
    print(f"Single option greeks: delta={sample_greeks.delta}, "
          f"gamma={sample_greeks.gamma}, theta={sample_greeks.theta}, "
          f"vega={sample_greeks.vega}")

    # In production:
    # greeks = await provider.get_greeks("AAPL250321C00150000")

    # --- 3. Portfolio greeks aggregation ---
    portfolio_greeks = AggregatedGreeks(
        total_delta=125.5,
        total_gamma=15.2,
        total_theta=-45.8,
        total_vega=230.0,
        position_count=5,
    )
    print(f"\nPortfolio greeks:")
    print(f"  Total delta: {portfolio_greeks.total_delta}")
    print(f"  Total gamma: {portfolio_greeks.total_gamma}")
    print(f"  Total theta: {portfolio_greeks.total_theta}")
    print(f"  Total vega:  {portfolio_greeks.total_vega}")
    print(f"  Positions:   {portfolio_greeks.position_count}")

    # In production:
    # positions = [MockPosition("AAPL250321C00150000", 5), ...]
    # agg = await provider.get_portfolio_greeks(positions)

    # --- 4. Cache invalidation ---
    # provider.invalidate("AAPL250321C00150000")  # single symbol
    # provider.invalidate()  # all cached greeks

    # --- 5. Risk monitoring via event bus ---
    async def on_greeks_risk(channel: str, data: object) -> None:
        print(f"  Risk event [{channel}]: {data}")

    await event_bus.subscribe("risk.greeks.*", on_greeks_risk)

    # The risk manager publishes greeks violations automatically.
    # Example of what the risk manager would publish:
    await event_bus.publish("risk.greeks.delta_exceeded", {
        "total_delta": 500.0,
        "limit": 300.0,
    })

    await asyncio.sleep(0.1)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
