"""Integration tests: greeks-aware risk checks wired into RiskManager."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_platform.core.enums import AssetClass, ContractType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Order, Position
from trading_platform.options.greeks import AggregatedGreeks, GreeksData, GreeksProvider
from trading_platform.risk.greeks_checks import GreeksRiskConfig
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig


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
        order_id="integ-1",
    )
    defaults.update(kwargs)
    return Order(**defaults)


def _equity_order(**kwargs) -> Order:
    defaults = dict(
        symbol="AAPL",
        quantity=Decimal("10"),
        order_id="integ-eq-1",
    )
    defaults.update(kwargs)
    return Order(**defaults)


def _mock_provider(portfolio_delta=0.0, portfolio_gamma=0.0, portfolio_theta=0.0, portfolio_vega=0.0, single_delta=0.3, single_gamma=0.02, single_vega=0.1):
    provider = AsyncMock(spec=GreeksProvider)
    provider.get_portfolio_greeks = AsyncMock(
        return_value=AggregatedGreeks(
            total_delta=portfolio_delta,
            total_gamma=portfolio_gamma,
            total_theta=portfolio_theta,
            total_vega=portfolio_vega,
        )
    )
    provider.get_greeks = AsyncMock(
        return_value=GreeksData(
            delta=single_delta,
            gamma=single_gamma,
            vega=single_vega,
        )
    )
    return provider


@pytest.fixture
def bus():
    return EventBus()


class TestGreeksIntegration:
    @pytest.mark.asyncio
    async def test_options_order_blocked_by_delta(self, bus):
        """Options order rejected when portfolio delta exceeds limit."""
        risk_config = RiskConfig(max_position_size=10000, max_order_value=1_000_000)
        rm = RiskManager(risk_config, bus)

        provider = _mock_provider(portfolio_delta=600.0)
        greeks_cfg = GreeksRiskConfig(max_portfolio_delta=500.0)
        rm.register_greeks_checks(provider, greeks_cfg)

        order = _option_order()
        passed, reason = await rm.pre_trade_check(order, [])
        assert passed is False
        assert "delta" in reason.lower()

    @pytest.mark.asyncio
    async def test_options_order_passes_when_within_limits(self, bus):
        """Options order passes when all greeks within limits."""
        risk_config = RiskConfig(max_position_size=10000, max_order_value=1_000_000)
        rm = RiskManager(risk_config, bus)

        provider = _mock_provider(portfolio_delta=100.0, portfolio_gamma=50.0, portfolio_theta=-100.0, portfolio_vega=500.0)
        greeks_cfg = GreeksRiskConfig(
            max_portfolio_delta=500.0,
            max_portfolio_gamma=100.0,
            max_daily_theta=-200.0,
            max_portfolio_vega=1000.0,
        )
        rm.register_greeks_checks(provider, greeks_cfg)

        order = _option_order()
        passed, reason = await rm.pre_trade_check(order, [])
        assert passed is True

    @pytest.mark.asyncio
    async def test_equity_order_skips_greeks(self, bus):
        """Equity orders bypass greeks checks entirely."""
        risk_config = RiskConfig(max_position_size=10000, max_order_value=1_000_000)
        rm = RiskManager(risk_config, bus)

        # Even with an absurd delta, equity orders should pass
        provider = _mock_provider(portfolio_delta=999999.0)
        greeks_cfg = GreeksRiskConfig(max_portfolio_delta=1.0)
        rm.register_greeks_checks(provider, greeks_cfg)

        order = _equity_order()
        passed, reason = await rm.pre_trade_check(order, [])
        assert passed is True

    @pytest.mark.asyncio
    async def test_no_greeks_provider_skips_checks(self, bus):
        """Without registering greeks, options orders still pass basic checks."""
        risk_config = RiskConfig(max_position_size=10000, max_order_value=1_000_000)
        rm = RiskManager(risk_config, bus)
        # Don't register greeks checks

        order = _option_order()
        passed, reason = await rm.pre_trade_check(order, [])
        assert passed is True

    @pytest.mark.asyncio
    async def test_greeks_violation_recorded(self, bus):
        """Greeks check failure records a RiskViolation."""
        risk_config = RiskConfig(max_position_size=10000, max_order_value=1_000_000)
        rm = RiskManager(risk_config, bus)

        provider = _mock_provider(portfolio_gamma=200.0)
        greeks_cfg = GreeksRiskConfig(max_portfolio_gamma=100.0)
        rm.register_greeks_checks(provider, greeks_cfg)

        order = _option_order()
        await rm.pre_trade_check(order, [])

        violations = rm.get_violations()
        assert len(violations) == 1
        assert violations[0]["check_name"] == "greeks"

    @pytest.mark.asyncio
    async def test_greeks_failure_publishes_event(self, bus):
        """Greeks check failure publishes risk.check.failed event."""
        received = []

        async def handler(ch, ev):
            received.append((ch, ev))

        await bus.subscribe("risk.check.failed", handler)

        risk_config = RiskConfig(max_position_size=10000, max_order_value=1_000_000)
        rm = RiskManager(risk_config, bus)

        provider = _mock_provider(portfolio_vega=2000.0)
        greeks_cfg = GreeksRiskConfig(max_portfolio_vega=1000.0)
        rm.register_greeks_checks(provider, greeks_cfg)

        order = _option_order()
        await rm.pre_trade_check(order, [])

        assert any(ch == "risk.check.failed" for ch, _ in received)
