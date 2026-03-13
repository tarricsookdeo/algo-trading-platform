"""Tests for greeks-aware risk checks."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_platform.core.enums import AssetClass, ContractType
from trading_platform.core.models import Order, Position
from trading_platform.options.greeks import AggregatedGreeks, GreeksData, GreeksProvider
from trading_platform.risk.greeks_checks import (
    GreeksRiskConfig,
    check_portfolio_delta,
    check_portfolio_gamma,
    check_single_position_greeks,
    check_theta_decay,
    check_vega_exposure,
)


# ── Fixtures / helpers ──────────────────────────────────────────────────


def _make_provider(agg: AggregatedGreeks | None = None, single: GreeksData | None = None):
    """Return a mock GreeksProvider with controllable return values."""
    provider = AsyncMock(spec=GreeksProvider)
    provider.get_portfolio_greeks = AsyncMock(
        return_value=agg or AggregatedGreeks()
    )
    provider.get_greeks = AsyncMock(
        return_value=single or GreeksData()
    )
    return provider


def _positions(count: int = 1) -> list[Position]:
    return [Position(symbol=f"OPT_{i}", quantity=Decimal("10")) for i in range(count)]


def _option_order(**kwargs) -> Order:
    defaults = dict(
        symbol="AAPL240119C00150000",
        asset_class=AssetClass.OPTION,
        contract_type=ContractType.CALL,
        strike_price=Decimal("150"),
        expiration_date="2024-01-19",
        underlying_symbol="AAPL",
        option_symbol="AAPL240119C00150000",
        quantity=Decimal("10"),
        order_id="test-order",
    )
    defaults.update(kwargs)
    return Order(**defaults)


# ── GreeksRiskConfig ────────────────────────────────────────────────────


class TestGreeksRiskConfig:
    def test_all_none_by_default(self):
        cfg = GreeksRiskConfig()
        assert cfg.max_portfolio_delta is None
        assert cfg.max_portfolio_gamma is None
        assert cfg.max_daily_theta is None
        assert cfg.max_portfolio_vega is None
        assert cfg.max_position_delta is None
        assert cfg.max_position_gamma is None
        assert cfg.max_position_vega is None

    def test_custom_values(self):
        cfg = GreeksRiskConfig(max_portfolio_delta=500.0, max_daily_theta=-200.0)
        assert cfg.max_portfolio_delta == 500.0
        assert cfg.max_daily_theta == -200.0


# ── check_portfolio_delta ───────────────────────────────────────────────


class TestCheckPortfolioDelta:
    @pytest.mark.asyncio
    async def test_disabled_when_none(self):
        provider = _make_provider()
        config = GreeksRiskConfig(max_portfolio_delta=None)
        passed, reason = await check_portfolio_delta(provider, _positions(), config)
        assert passed is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_within_limit(self):
        agg = AggregatedGreeks(total_delta=400.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_portfolio_delta=500.0)
        passed, _ = await check_portfolio_delta(provider, _positions(), config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_exceeds_limit(self):
        agg = AggregatedGreeks(total_delta=600.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_portfolio_delta=500.0)
        passed, reason = await check_portfolio_delta(provider, _positions(), config)
        assert passed is False
        assert "delta" in reason.lower()

    @pytest.mark.asyncio
    async def test_negative_delta_uses_abs(self):
        agg = AggregatedGreeks(total_delta=-600.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_portfolio_delta=500.0)
        passed, _ = await check_portfolio_delta(provider, _positions(), config)
        assert passed is False


# ── check_portfolio_gamma ──────────────────────────────────────────────


class TestCheckPortfolioGamma:
    @pytest.mark.asyncio
    async def test_disabled_when_none(self):
        provider = _make_provider()
        config = GreeksRiskConfig(max_portfolio_gamma=None)
        passed, _ = await check_portfolio_gamma(provider, _positions(), config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_within_limit(self):
        agg = AggregatedGreeks(total_gamma=80.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_portfolio_gamma=100.0)
        passed, _ = await check_portfolio_gamma(provider, _positions(), config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_exceeds_limit(self):
        agg = AggregatedGreeks(total_gamma=150.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_portfolio_gamma=100.0)
        passed, reason = await check_portfolio_gamma(provider, _positions(), config)
        assert passed is False
        assert "gamma" in reason.lower()


# ── check_theta_decay ──────────────────────────────────────────────────


class TestCheckThetaDecay:
    @pytest.mark.asyncio
    async def test_disabled_when_none(self):
        provider = _make_provider()
        config = GreeksRiskConfig(max_daily_theta=None)
        passed, _ = await check_theta_decay(provider, _positions(), config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_within_limit(self):
        agg = AggregatedGreeks(total_theta=-100.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_daily_theta=-200.0)
        passed, _ = await check_theta_decay(provider, _positions(), config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_exceeds_limit(self):
        """Theta more negative than the threshold triggers failure."""
        agg = AggregatedGreeks(total_theta=-250.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_daily_theta=-200.0)
        passed, reason = await check_theta_decay(provider, _positions(), config)
        assert passed is False
        assert "theta" in reason.lower()

    @pytest.mark.asyncio
    async def test_exactly_at_limit(self):
        agg = AggregatedGreeks(total_theta=-200.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_daily_theta=-200.0)
        passed, _ = await check_theta_decay(provider, _positions(), config)
        assert passed is True  # equal is not exceeded


# ── check_vega_exposure ────────────────────────────────────────────────


class TestCheckVegaExposure:
    @pytest.mark.asyncio
    async def test_disabled_when_none(self):
        provider = _make_provider()
        config = GreeksRiskConfig(max_portfolio_vega=None)
        passed, _ = await check_vega_exposure(provider, _positions(), config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_within_limit(self):
        agg = AggregatedGreeks(total_vega=800.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_portfolio_vega=1000.0)
        passed, _ = await check_vega_exposure(provider, _positions(), config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_exceeds_limit(self):
        agg = AggregatedGreeks(total_vega=1200.0)
        provider = _make_provider(agg=agg)
        config = GreeksRiskConfig(max_portfolio_vega=1000.0)
        passed, reason = await check_vega_exposure(provider, _positions(), config)
        assert passed is False
        assert "vega" in reason.lower()


# ── check_single_position_greeks ───────────────────────────────────────


class TestCheckSinglePositionGreeks:
    @pytest.mark.asyncio
    async def test_all_limits_disabled(self):
        provider = _make_provider()
        config = GreeksRiskConfig()
        order = _option_order()
        passed, _ = await check_single_position_greeks(provider, order, config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_delta_within_limit(self):
        single = GreeksData(delta=0.5)
        provider = _make_provider(single=single)
        config = GreeksRiskConfig(max_position_delta=10.0)
        order = _option_order(quantity=Decimal("10"))
        passed, _ = await check_single_position_greeks(provider, order, config)
        assert passed is True  # 0.5 * 10 = 5.0 < 10.0

    @pytest.mark.asyncio
    async def test_delta_exceeds_limit(self):
        single = GreeksData(delta=0.8)
        provider = _make_provider(single=single)
        config = GreeksRiskConfig(max_position_delta=5.0)
        order = _option_order(quantity=Decimal("10"))
        passed, reason = await check_single_position_greeks(provider, order, config)
        assert passed is False  # 0.8 * 10 = 8.0 > 5.0
        assert "delta" in reason.lower()

    @pytest.mark.asyncio
    async def test_gamma_exceeds_limit(self):
        single = GreeksData(gamma=0.1)
        provider = _make_provider(single=single)
        config = GreeksRiskConfig(max_position_gamma=0.5)
        order = _option_order(quantity=Decimal("10"))
        passed, reason = await check_single_position_greeks(provider, order, config)
        assert passed is False  # 0.1 * 10 = 1.0 > 0.5
        assert "gamma" in reason.lower()

    @pytest.mark.asyncio
    async def test_vega_exceeds_limit(self):
        single = GreeksData(vega=0.2)
        provider = _make_provider(single=single)
        config = GreeksRiskConfig(max_position_vega=1.0)
        order = _option_order(quantity=Decimal("10"))
        passed, reason = await check_single_position_greeks(provider, order, config)
        assert passed is False  # 0.2 * 10 = 2.0 > 1.0
        assert "vega" in reason.lower()

    @pytest.mark.asyncio
    async def test_fetch_error_allows_order(self):
        """Fail-open: if greeks fetch fails, allow the order."""
        provider = _make_provider()
        provider.get_greeks = AsyncMock(side_effect=RuntimeError("API down"))
        config = GreeksRiskConfig(max_position_delta=1.0)
        order = _option_order()
        passed, _ = await check_single_position_greeks(provider, order, config)
        assert passed is True

    @pytest.mark.asyncio
    async def test_no_symbol_allows_order(self):
        """Orders without option_symbol or symbol pass through."""
        provider = _make_provider()
        config = GreeksRiskConfig(max_position_delta=1.0)
        # Create equity order (no option_symbol, no validation issue)
        order = Order(symbol="", quantity=Decimal("10"), order_id="test")
        passed, _ = await check_single_position_greeks(provider, order, config)
        assert passed is True
