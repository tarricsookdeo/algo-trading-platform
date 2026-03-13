"""Validates strategy parameters and computes risk/reward analysis."""

from __future__ import annotations

from decimal import Decimal

from trading_platform.core.enums import ContractType
from trading_platform.core.models import MultiLegOrder
from trading_platform.options.strategies import (
    ButterflySpreadParams,
    CalendarSpreadParams,
    IronCondorParams,
    StraddleParams,
    StrangleParams,
    StrategyAnalysis,
    VerticalSpreadParams,
)

# Contract multiplier (standard equity options = 100 shares per contract)
_MULTIPLIER = Decimal("100")


class StrategyValidationError(Exception):
    """Raised when a strategy fails validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class StrategyValidator:
    """Validates strategy parameters and computes max profit/loss/breakevens."""

    # ── Parameter validation ─────────────────────────────────────────

    def validate_vertical_spread(self, params: VerticalSpreadParams) -> StrategyAnalysis:
        errors: list[str] = []
        self._check_quantity(params.quantity, errors)
        if params.long_strike == params.short_strike:
            errors.append("long_strike and short_strike must differ")
        if errors:
            return StrategyAnalysis(errors=errors)
        return self._analyze_vertical(params)

    def validate_iron_condor(self, params: IronCondorParams) -> StrategyAnalysis:
        errors: list[str] = []
        self._check_quantity(params.quantity, errors)
        if not (params.put_long_strike < params.put_short_strike):
            errors.append("put_long_strike must be less than put_short_strike")
        if not (params.put_short_strike < params.call_short_strike):
            errors.append("put_short_strike must be less than call_short_strike")
        if not (params.call_short_strike < params.call_long_strike):
            errors.append("call_short_strike must be less than call_long_strike")
        if errors:
            return StrategyAnalysis(errors=errors)
        return self._analyze_iron_condor(params)

    def validate_straddle(self, params: StraddleParams) -> StrategyAnalysis:
        errors: list[str] = []
        self._check_quantity(params.quantity, errors)
        if params.side not in ("long", "short"):
            errors.append("side must be 'long' or 'short'")
        if errors:
            return StrategyAnalysis(errors=errors)
        return self._analyze_straddle(params)

    def validate_strangle(self, params: StrangleParams) -> StrategyAnalysis:
        errors: list[str] = []
        self._check_quantity(params.quantity, errors)
        if params.side not in ("long", "short"):
            errors.append("side must be 'long' or 'short'")
        if not (params.put_strike < params.call_strike):
            errors.append("put_strike must be less than call_strike")
        if errors:
            return StrategyAnalysis(errors=errors)
        return self._analyze_strangle(params)

    def validate_butterfly_spread(self, params: ButterflySpreadParams) -> StrategyAnalysis:
        errors: list[str] = []
        self._check_quantity(params.quantity, errors)
        if not (params.lower_strike < params.middle_strike < params.upper_strike):
            errors.append("strikes must be in order: lower < middle < upper")
        wing_width_low = params.middle_strike - params.lower_strike
        wing_width_high = params.upper_strike - params.middle_strike
        if wing_width_low != wing_width_high:
            errors.append("wing widths must be equal (middle - lower must equal upper - middle)")
        if errors:
            return StrategyAnalysis(errors=errors)
        return self._analyze_butterfly(params)

    def validate_calendar_spread(self, params: CalendarSpreadParams) -> StrategyAnalysis:
        errors: list[str] = []
        self._check_quantity(params.quantity, errors)
        if params.expiration_near >= params.expiration_far:
            errors.append("expiration_near must be before expiration_far")
        if errors:
            return StrategyAnalysis(errors=errors)
        # Calendar spread P/L depends on IV and time decay — cannot determine exact max P/L
        return StrategyAnalysis(max_profit=None, max_loss=None, breakevens=[])

    def validate_multileg_order(self, order: MultiLegOrder) -> StrategyAnalysis:
        """Generic validation for any MultiLegOrder: same underlying, consistent expirations."""
        errors: list[str] = []
        if not order.legs:
            errors.append("MultiLegOrder has no legs")
            return StrategyAnalysis(errors=errors)

        underlyings = {leg.underlying_symbol for leg in order.legs}
        if len(underlyings) > 1:
            errors.append(f"All legs must use the same underlying, found: {sorted(underlyings)}")

        # For non-calendar strategies, all expirations should match
        expirations = {leg.expiration_date for leg in order.legs}
        if order.strategy_type != "calendar_spread" and len(expirations) > 1:
            errors.append(f"All legs must have the same expiration (except calendar spreads), found: {sorted(str(e) for e in expirations)}")

        return StrategyAnalysis(errors=errors) if errors else StrategyAnalysis()

    # ── Risk/reward analysis ─────────────────────────────────────────

    def _analyze_vertical(self, params: VerticalSpreadParams) -> StrategyAnalysis:
        width = abs(params.long_strike - params.short_strike)
        scaled_width = width * _MULTIPLIER * params.quantity

        if params.contract_type == ContractType.CALL:
            if params.long_strike < params.short_strike:
                # Bull call spread: buy lower call, sell higher call
                # Max profit = (width * 100 * qty) - debit; debit unknown, use width-based
                # Simplified: max profit = width * multiplier * qty (net of debit)
                # Since we don't have premiums, express in terms of spread width
                return StrategyAnalysis(
                    max_profit=scaled_width,
                    max_loss=scaled_width,
                    breakevens=[params.long_strike],
                )
            else:
                # Bear call spread: buy higher call, sell lower call (credit spread)
                return StrategyAnalysis(
                    max_profit=scaled_width,
                    max_loss=scaled_width,
                    breakevens=[params.short_strike],
                )
        else:  # PUT
            if params.long_strike > params.short_strike:
                # Bear put spread: buy higher put, sell lower put (debit spread)
                return StrategyAnalysis(
                    max_profit=scaled_width,
                    max_loss=scaled_width,
                    breakevens=[params.long_strike],
                )
            else:
                # Bull put spread: buy lower put, sell higher put (credit spread)
                return StrategyAnalysis(
                    max_profit=scaled_width,
                    max_loss=scaled_width,
                    breakevens=[params.short_strike],
                )

    def _analyze_iron_condor(self, params: IronCondorParams) -> StrategyAnalysis:
        put_width = (params.put_short_strike - params.put_long_strike) * _MULTIPLIER * params.quantity
        call_width = (params.call_long_strike - params.call_short_strike) * _MULTIPLIER * params.quantity
        max_loss = max(put_width, call_width)
        # Max profit = net credit received (unknown without premiums); express as the wider wing
        max_profit = max_loss  # placeholder — symmetric when wings are equal width
        lower_be = params.put_short_strike
        upper_be = params.call_short_strike
        return StrategyAnalysis(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[lower_be, upper_be],
        )

    def _analyze_straddle(self, params: StraddleParams) -> StrategyAnalysis:
        # Without premiums, express in terms of strike
        if params.side == "long":
            # Long straddle: max loss = premium paid (unknown); max profit = unlimited
            return StrategyAnalysis(
                max_profit=None,  # unlimited
                max_loss=None,  # equal to premium paid
                breakevens=[params.strike],
            )
        else:
            # Short straddle: max profit = premium received; max loss = unlimited
            return StrategyAnalysis(
                max_profit=None,  # equal to premium received
                max_loss=None,  # unlimited
                breakevens=[params.strike],
            )

    def _analyze_strangle(self, params: StrangleParams) -> StrategyAnalysis:
        if params.side == "long":
            return StrategyAnalysis(
                max_profit=None,  # unlimited
                max_loss=None,  # equal to total premium paid
                breakevens=[params.put_strike, params.call_strike],
            )
        else:
            return StrategyAnalysis(
                max_profit=None,  # equal to total premium received
                max_loss=None,  # unlimited
                breakevens=[params.put_strike, params.call_strike],
            )

    def _analyze_butterfly(self, params: ButterflySpreadParams) -> StrategyAnalysis:
        wing_width = (params.middle_strike - params.lower_strike) * _MULTIPLIER * params.quantity
        max_profit = wing_width  # max at expiration if underlying at middle strike
        max_loss = wing_width  # net debit (without premiums, express as wing width)
        lower_be = params.lower_strike
        upper_be = params.upper_strike
        return StrategyAnalysis(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[lower_be, upper_be],
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _check_quantity(quantity: Decimal, errors: list[str]) -> None:
        if quantity <= 0:
            errors.append("quantity must be positive")
