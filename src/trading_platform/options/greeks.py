"""Greeks provider — fetches, caches, and aggregates option greeks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from trading_platform.core.logging import get_logger


@dataclass(frozen=True)
class GreeksData:
    """Greeks snapshot for a single option contract."""

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    implied_volatility: float = 0.0
    timestamp: float = 0.0  # monotonic seconds


@dataclass(frozen=True)
class AggregatedGreeks:
    """Portfolio-level aggregated greeks."""

    total_delta: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0
    position_count: int = 0


class GreeksProvider:
    """Fetches greeks from Public.com SDK and caches them.

    Parameters
    ----------
    client:
        An ``OptionsClient`` (or any object with a ``.raw`` attribute
        exposing the ``AsyncPublicApiClient``).
    refresh_interval:
        Seconds before a cached entry is considered stale (default 30).
    """

    def __init__(self, client: Any, refresh_interval: float = 30.0) -> None:
        self._client = client
        self._refresh_interval = refresh_interval
        self._cache: dict[str, tuple[GreeksData, float]] = {}
        self._log = get_logger("options.greeks")

    # ── Public API ────────────────────────────────────────────────────

    async def get_greeks(self, option_symbol: str) -> GreeksData:
        """Return greeks for *option_symbol*, using cache when fresh."""
        cached = self._cache.get(option_symbol)
        now = time.monotonic()
        if cached and (now - cached[1]) < self._refresh_interval:
            return cached[0]

        greeks = await self._fetch_greeks(option_symbol)
        self._cache[option_symbol] = (greeks, now)
        return greeks

    async def get_portfolio_greeks(self, positions: list[Any]) -> AggregatedGreeks:
        """Aggregate greeks across all *positions*.

        Each position must have ``symbol`` and ``quantity`` attributes.
        """
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        count = 0

        for pos in positions:
            try:
                greeks = await self.get_greeks(pos.symbol)
            except Exception:
                self._log.warning(
                    "failed to fetch greeks for position",
                    symbol=pos.symbol,
                )
                continue
            qty = float(pos.quantity)
            total_delta += greeks.delta * qty
            total_gamma += greeks.gamma * qty
            total_theta += greeks.theta * qty
            total_vega += greeks.vega * qty
            count += 1

        return AggregatedGreeks(
            total_delta=total_delta,
            total_gamma=total_gamma,
            total_theta=total_theta,
            total_vega=total_vega,
            position_count=count,
        )

    def invalidate(self, option_symbol: str | None = None) -> None:
        """Drop cached greeks.  If *option_symbol* is ``None``, clear all."""
        if option_symbol is None:
            self._cache.clear()
        else:
            self._cache.pop(option_symbol, None)

    # ── Internal ──────────────────────────────────────────────────────

    async def _fetch_greeks(self, option_symbol: str) -> GreeksData:
        """Call the SDK to retrieve greeks for a single option."""
        raw = self._client.raw
        result = await raw.get_option_greeks(option_symbol)

        return GreeksData(
            delta=float(getattr(result, "delta", 0) or 0),
            gamma=float(getattr(result, "gamma", 0) or 0),
            theta=float(getattr(result, "theta", 0) or 0),
            vega=float(getattr(result, "vega", 0) or 0),
            rho=float(getattr(result, "rho", 0) or 0),
            implied_volatility=float(
                getattr(result, "implied_volatility", 0)
                or getattr(result, "iv", 0)
                or 0
            ),
            timestamp=time.monotonic(),
        )
