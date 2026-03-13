"""OptionsStrategyBuilder — constructs multi-leg options orders for common strategies."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from trading_platform.core.enums import (
    AssetClass,
    ContractType,
    OrderSide,
    OrderType,
)
from trading_platform.core.models import MultiLegOrder, Order
from trading_platform.options.strategies import (
    ButterflySpreadParams,
    CalendarSpreadParams,
    IronCondorParams,
    StraddleParams,
    StrangleParams,
    StrategyAnalysis,
    VerticalSpreadParams,
)
from trading_platform.options.validator import StrategyValidationError, StrategyValidator


def _option_leg(
    underlying: str,
    expiration: Any,
    strike: Decimal,
    contract_type: ContractType,
    side: OrderSide,
    quantity: Decimal,
) -> Order:
    """Build a single option leg Order."""
    ct_char = "C" if contract_type == ContractType.CALL else "P"
    option_symbol = f"{underlying}{expiration:%y%m%d}{ct_char}{int(strike * 1000):08d}"
    return Order(
        order_id=str(uuid.uuid4()),
        symbol=option_symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        asset_class=AssetClass.OPTION,
        contract_type=contract_type,
        strike_price=strike,
        expiration_date=expiration,
        underlying_symbol=underlying,
        option_symbol=option_symbol,
    )


class OptionsStrategyBuilder:
    """Builds validated MultiLegOrder instances for common options strategies.

    Each ``build_*`` method validates parameters, constructs the legs, and
    returns a ``MultiLegOrder`` ready for submission via ``OrderRouter``.
    """

    def __init__(self) -> None:
        self._validator = StrategyValidator()

    # ── Vertical Spread ──────────────────────────────────────────────

    def build_vertical_spread(self, params: VerticalSpreadParams) -> MultiLegOrder:
        """Build a vertical (bull/bear call/put) spread.

        The leg with ``long_strike`` is bought, the leg with ``short_strike``
        is sold.  Whether this forms a debit or credit spread depends on the
        contract type and relative strike positions.
        """
        analysis = self._validator.validate_vertical_spread(params)
        self._raise_if_invalid(analysis)

        buy_leg = _option_leg(
            params.underlying,
            params.expiration,
            params.long_strike,
            params.contract_type,
            OrderSide.BUY,
            params.quantity,
        )
        sell_leg = _option_leg(
            params.underlying,
            params.expiration,
            params.short_strike,
            params.contract_type,
            OrderSide.SELL,
            params.quantity,
        )
        return self._make_multileg("vertical_spread", [buy_leg, sell_leg])

    # ── Iron Condor ──────────────────────────────────────────────────

    def build_iron_condor(self, params: IronCondorParams) -> MultiLegOrder:
        """Build an iron condor (sell a put spread + sell a call spread)."""
        analysis = self._validator.validate_iron_condor(params)
        self._raise_if_invalid(analysis)

        legs = [
            # Put spread: buy OTM put, sell closer put
            _option_leg(params.underlying, params.expiration, params.put_long_strike, ContractType.PUT, OrderSide.BUY, params.quantity),
            _option_leg(params.underlying, params.expiration, params.put_short_strike, ContractType.PUT, OrderSide.SELL, params.quantity),
            # Call spread: sell closer call, buy OTM call
            _option_leg(params.underlying, params.expiration, params.call_short_strike, ContractType.CALL, OrderSide.SELL, params.quantity),
            _option_leg(params.underlying, params.expiration, params.call_long_strike, ContractType.CALL, OrderSide.BUY, params.quantity),
        ]
        return self._make_multileg("iron_condor", legs)

    # ── Straddle ─────────────────────────────────────────────────────

    def build_straddle(self, params: StraddleParams) -> MultiLegOrder:
        """Build a long or short straddle (same strike call + put)."""
        analysis = self._validator.validate_straddle(params)
        self._raise_if_invalid(analysis)

        if params.side == "long":
            call_side = OrderSide.BUY
            put_side = OrderSide.BUY
        else:
            call_side = OrderSide.SELL
            put_side = OrderSide.SELL

        legs = [
            _option_leg(params.underlying, params.expiration, params.strike, ContractType.CALL, call_side, params.quantity),
            _option_leg(params.underlying, params.expiration, params.strike, ContractType.PUT, put_side, params.quantity),
        ]
        return self._make_multileg("straddle", legs)

    # ── Strangle ─────────────────────────────────────────────────────

    def build_strangle(self, params: StrangleParams) -> MultiLegOrder:
        """Build a long or short strangle (different strike call + put)."""
        analysis = self._validator.validate_strangle(params)
        self._raise_if_invalid(analysis)

        if params.side == "long":
            call_side = OrderSide.BUY
            put_side = OrderSide.BUY
        else:
            call_side = OrderSide.SELL
            put_side = OrderSide.SELL

        legs = [
            _option_leg(params.underlying, params.expiration, params.put_strike, ContractType.PUT, put_side, params.quantity),
            _option_leg(params.underlying, params.expiration, params.call_strike, ContractType.CALL, call_side, params.quantity),
        ]
        return self._make_multileg("strangle", legs)

    # ── Butterfly Spread ─────────────────────────────────────────────

    def build_butterfly_spread(self, params: ButterflySpreadParams) -> MultiLegOrder:
        """Build a long butterfly spread (buy lower + upper, sell 2x middle)."""
        analysis = self._validator.validate_butterfly_spread(params)
        self._raise_if_invalid(analysis)

        legs = [
            _option_leg(params.underlying, params.expiration, params.lower_strike, params.contract_type, OrderSide.BUY, params.quantity),
            _option_leg(params.underlying, params.expiration, params.middle_strike, params.contract_type, OrderSide.SELL, params.quantity * 2),
            _option_leg(params.underlying, params.expiration, params.upper_strike, params.contract_type, OrderSide.BUY, params.quantity),
        ]
        return self._make_multileg("butterfly_spread", legs)

    # ── Calendar Spread ──────────────────────────────────────────────

    def build_calendar_spread(self, params: CalendarSpreadParams) -> MultiLegOrder:
        """Build a calendar spread (sell near-term, buy far-term at same strike)."""
        analysis = self._validator.validate_calendar_spread(params)
        self._raise_if_invalid(analysis)

        legs = [
            _option_leg(params.underlying, params.expiration_near, params.strike, params.contract_type, OrderSide.SELL, params.quantity),
            _option_leg(params.underlying, params.expiration_far, params.strike, params.contract_type, OrderSide.BUY, params.quantity),
        ]
        return self._make_multileg("calendar_spread", legs)

    # ── Build and submit convenience ─────────────────────────────────

    async def build_and_submit(
        self,
        strategy_params: VerticalSpreadParams | IronCondorParams | StraddleParams | StrangleParams | ButterflySpreadParams | CalendarSpreadParams,
        order_router: Any,
    ) -> MultiLegOrder:
        """Build a strategy, validate it, and submit via the order router.

        Returns the MultiLegOrder with its status updated after submission.
        """
        builders = {
            VerticalSpreadParams: self.build_vertical_spread,
            IronCondorParams: self.build_iron_condor,
            StraddleParams: self.build_straddle,
            StrangleParams: self.build_strangle,
            ButterflySpreadParams: self.build_butterfly_spread,
            CalendarSpreadParams: self.build_calendar_spread,
        }
        builder = builders.get(type(strategy_params))
        if builder is None:
            raise TypeError(f"Unknown strategy params type: {type(strategy_params).__name__}")

        multileg = builder(strategy_params)

        # Run generic multi-leg validation (same underlying, consistent expirations)
        analysis = self._validator.validate_multileg_order(multileg)
        self._raise_if_invalid(analysis)

        await order_router.submit_multileg_order(multileg)
        return multileg

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _make_multileg(strategy_type: str, legs: list[Order]) -> MultiLegOrder:
        return MultiLegOrder(
            id=str(uuid.uuid4()),
            legs=legs,
            strategy_type=strategy_type,
        )

    @staticmethod
    def _raise_if_invalid(analysis: StrategyAnalysis) -> None:
        if not analysis.is_valid:
            raise StrategyValidationError(analysis.errors)
