"""Tests for GreeksProvider — fetch, cache, expiry, aggregation."""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_platform.core.models import Position
from trading_platform.options.greeks import AggregatedGreeks, GreeksData, GreeksProvider


# ── Helpers ─────────────────────────────────────────────────────────────


def _mock_client(greeks_map: dict[str, dict] | None = None):
    """Return a mock client whose `.raw.get_option_greeks` returns configured data."""
    defaults = {
        "delta": 0.5,
        "gamma": 0.05,
        "theta": -0.03,
        "vega": 0.12,
        "rho": 0.01,
        "implied_volatility": 0.30,
    }
    greeks_map = greeks_map or {}

    raw = AsyncMock()

    async def _get_greeks(symbol: str):
        data = greeks_map.get(symbol, defaults)
        result = MagicMock()
        for k, v in data.items():
            setattr(result, k, v)
        return result

    raw.get_option_greeks = _get_greeks
    client = MagicMock()
    client.raw = raw
    return client


# ── GreeksData / AggregatedGreeks models ───────────────────────────────


class TestGreeksDataModel:
    def test_defaults(self):
        g = GreeksData()
        assert g.delta == 0.0
        assert g.gamma == 0.0
        assert g.theta == 0.0
        assert g.vega == 0.0
        assert g.rho == 0.0
        assert g.implied_volatility == 0.0
        assert g.timestamp == 0.0

    def test_frozen(self):
        g = GreeksData(delta=0.5)
        with pytest.raises(AttributeError):
            g.delta = 1.0  # type: ignore[misc]


class TestAggregatedGreeksModel:
    def test_defaults(self):
        a = AggregatedGreeks()
        assert a.total_delta == 0.0
        assert a.position_count == 0


# ── GreeksProvider.get_greeks ──────────────────────────────────────────


class TestGetGreeks:
    @pytest.mark.asyncio
    async def test_fetch_returns_greeks(self):
        client = _mock_client()
        provider = GreeksProvider(client, refresh_interval=30.0)
        g = await provider.get_greeks("AAPL240119C00150000")
        assert g.delta == 0.5
        assert g.gamma == 0.05
        assert g.theta == -0.03
        assert g.vega == 0.12

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        client = _mock_client()
        provider = GreeksProvider(client, refresh_interval=30.0)
        g1 = await provider.get_greeks("AAPL240119C00150000")
        g2 = await provider.get_greeks("AAPL240119C00150000")
        assert g1 is g2  # same cached object

    @pytest.mark.asyncio
    async def test_cache_expiry(self, monkeypatch):
        """Expired cache entry triggers a re-fetch."""
        client = _mock_client()
        provider = GreeksProvider(client, refresh_interval=0.0)  # immediate expiry
        g1 = await provider.get_greeks("AAPL240119C00150000")
        g2 = await provider.get_greeks("AAPL240119C00150000")
        # With refresh_interval=0, every call is a cache miss → different objects
        assert g1 is not g2

    @pytest.mark.asyncio
    async def test_handles_missing_attrs(self):
        """Gracefully handles SDK result missing some attributes."""
        raw = AsyncMock()

        async def _sparse_greeks(symbol):
            result = MagicMock(spec=[])  # no attrs
            return result

        raw.get_option_greeks = _sparse_greeks
        client = MagicMock()
        client.raw = raw
        provider = GreeksProvider(client)
        g = await provider.get_greeks("XYZ")
        assert g.delta == 0.0
        assert g.implied_volatility == 0.0


# ── GreeksProvider.get_portfolio_greeks ────────────────────────────────


class TestGetPortfolioGreeks:
    @pytest.mark.asyncio
    async def test_aggregation(self):
        greeks_map = {
            "OPT_A": {"delta": 0.5, "gamma": 0.04, "theta": -0.02, "vega": 0.10, "rho": 0, "implied_volatility": 0},
            "OPT_B": {"delta": -0.3, "gamma": 0.02, "theta": -0.01, "vega": 0.05, "rho": 0, "implied_volatility": 0},
        }
        client = _mock_client(greeks_map)
        provider = GreeksProvider(client)
        positions = [
            Position(symbol="OPT_A", quantity=Decimal("10")),
            Position(symbol="OPT_B", quantity=Decimal("20")),
        ]
        agg = await provider.get_portfolio_greeks(positions)
        assert agg.total_delta == pytest.approx(0.5 * 10 + (-0.3) * 20)
        assert agg.total_gamma == pytest.approx(0.04 * 10 + 0.02 * 20)
        assert agg.total_theta == pytest.approx(-0.02 * 10 + -0.01 * 20)
        assert agg.total_vega == pytest.approx(0.10 * 10 + 0.05 * 20)
        assert agg.position_count == 2

    @pytest.mark.asyncio
    async def test_empty_positions(self):
        client = _mock_client()
        provider = GreeksProvider(client)
        agg = await provider.get_portfolio_greeks([])
        assert agg.total_delta == 0.0
        assert agg.position_count == 0

    @pytest.mark.asyncio
    async def test_skips_failed_fetch(self):
        """If one position fails, it's skipped and the rest still aggregate."""
        raw = AsyncMock()
        call_count = 0

        async def _flaky_greeks(symbol):
            nonlocal call_count
            call_count += 1
            if symbol == "BAD":
                raise RuntimeError("API error")
            result = MagicMock()
            result.delta = 0.5
            result.gamma = 0.05
            result.theta = -0.03
            result.vega = 0.12
            result.rho = 0.01
            result.implied_volatility = 0.30
            return result

        raw.get_option_greeks = _flaky_greeks
        client = MagicMock()
        client.raw = raw
        provider = GreeksProvider(client)
        positions = [
            Position(symbol="GOOD", quantity=Decimal("10")),
            Position(symbol="BAD", quantity=Decimal("5")),
        ]
        agg = await provider.get_portfolio_greeks(positions)
        assert agg.position_count == 1
        assert agg.total_delta == pytest.approx(0.5 * 10)


# ── GreeksProvider.invalidate ──────────────────────────────────────────


class TestInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_single(self):
        client = _mock_client()
        provider = GreeksProvider(client, refresh_interval=9999)
        await provider.get_greeks("SYM_A")
        await provider.get_greeks("SYM_B")
        provider.invalidate("SYM_A")
        # SYM_B still cached
        assert "SYM_B" in provider._cache
        assert "SYM_A" not in provider._cache

    @pytest.mark.asyncio
    async def test_invalidate_all(self):
        client = _mock_client()
        provider = GreeksProvider(client, refresh_interval=9999)
        await provider.get_greeks("SYM_A")
        await provider.get_greeks("SYM_B")
        provider.invalidate()
        assert len(provider._cache) == 0
