"""Greeks-aware risk checks for options positions.

Each check is an async function returning ``(passed, reason)`` consistent
with the synchronous checks in ``checks.py``.  They are async because they
must query the :class:`GreeksProvider` to fetch current greeks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_platform.core.models import Order, Position
from trading_platform.options.greeks import AggregatedGreeks, GreeksProvider


@dataclass
class GreeksRiskConfig:
    """Configuration for greeks-based risk limits.

    All limits are optional — a value of ``None`` disables the check.
    """

    max_portfolio_delta: float | None = None
    max_portfolio_gamma: float | None = None
    max_daily_theta: float | None = None  # negative value, e.g. -200
    max_portfolio_vega: float | None = None
    # Per-position limits
    max_position_delta: float | None = None
    max_position_gamma: float | None = None
    max_position_vega: float | None = None
    greeks_refresh_interval_seconds: float = 30.0


async def check_portfolio_delta(
    provider: GreeksProvider,
    positions: list[Position],
    config: GreeksRiskConfig,
) -> tuple[bool, str]:
    """Reject if total portfolio delta exceeds *max_portfolio_delta*."""
    if config.max_portfolio_delta is None:
        return True, ""
    agg = await provider.get_portfolio_greeks(positions)
    if abs(agg.total_delta) > config.max_portfolio_delta:
        return (
            False,
            f"Portfolio delta {agg.total_delta:.2f} exceeds limit "
            f"{config.max_portfolio_delta:.2f}",
        )
    return True, ""


async def check_portfolio_gamma(
    provider: GreeksProvider,
    positions: list[Position],
    config: GreeksRiskConfig,
) -> tuple[bool, str]:
    """Reject if total portfolio gamma exceeds *max_portfolio_gamma*."""
    if config.max_portfolio_gamma is None:
        return True, ""
    agg = await provider.get_portfolio_greeks(positions)
    if abs(agg.total_gamma) > config.max_portfolio_gamma:
        return (
            False,
            f"Portfolio gamma {agg.total_gamma:.2f} exceeds limit "
            f"{config.max_portfolio_gamma:.2f}",
        )
    return True, ""


async def check_theta_decay(
    provider: GreeksProvider,
    positions: list[Position],
    config: GreeksRiskConfig,
) -> tuple[bool, str]:
    """Reject if daily theta decay exceeds (is more negative than) threshold."""
    if config.max_daily_theta is None:
        return True, ""
    agg = await provider.get_portfolio_greeks(positions)
    # theta is normally negative; threshold is also negative, e.g. -200
    if agg.total_theta < config.max_daily_theta:
        return (
            False,
            f"Daily theta {agg.total_theta:.2f} exceeds limit "
            f"{config.max_daily_theta:.2f}",
        )
    return True, ""


async def check_vega_exposure(
    provider: GreeksProvider,
    positions: list[Position],
    config: GreeksRiskConfig,
) -> tuple[bool, str]:
    """Reject if total vega exceeds *max_portfolio_vega*."""
    if config.max_portfolio_vega is None:
        return True, ""
    agg = await provider.get_portfolio_greeks(positions)
    if abs(agg.total_vega) > config.max_portfolio_vega:
        return (
            False,
            f"Portfolio vega {agg.total_vega:.2f} exceeds limit "
            f"{config.max_portfolio_vega:.2f}",
        )
    return True, ""


async def check_single_position_greeks(
    provider: GreeksProvider,
    order: Order,
    config: GreeksRiskConfig,
) -> tuple[bool, str]:
    """Per-position greeks limits applied to the order's option contract."""
    symbol = order.option_symbol or order.symbol
    if not symbol:
        return True, ""

    try:
        greeks = await provider.get_greeks(symbol)
    except Exception:
        # If we can't fetch greeks, allow the order (fail-open for single check).
        return True, ""

    qty = float(order.quantity)

    if config.max_position_delta is not None:
        pos_delta = abs(greeks.delta * qty)
        if pos_delta > config.max_position_delta:
            return (
                False,
                f"Position delta {pos_delta:.2f} exceeds limit "
                f"{config.max_position_delta:.2f} for {symbol}",
            )

    if config.max_position_gamma is not None:
        pos_gamma = abs(greeks.gamma * qty)
        if pos_gamma > config.max_position_gamma:
            return (
                False,
                f"Position gamma {pos_gamma:.2f} exceeds limit "
                f"{config.max_position_gamma:.2f} for {symbol}",
            )

    if config.max_position_vega is not None:
        pos_vega = abs(greeks.vega * qty)
        if pos_vega > config.max_position_vega:
            return (
                False,
                f"Position vega {pos_vega:.2f} exceeds limit "
                f"{config.max_position_vega:.2f} for {symbol}",
            )

    return True, ""
