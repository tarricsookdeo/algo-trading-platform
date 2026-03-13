"""Tests for the options strategy builder, validator, and strategy-context integration."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_platform.core.enums import (
    AssetClass,
    ContractType,
    OrderSide,
    OrderStatus,
    OrderType,
)
from trading_platform.core.events import EventBus
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
from trading_platform.options.strategy_builder import OptionsStrategyBuilder
from trading_platform.options.validator import StrategyValidationError, StrategyValidator
from trading_platform.strategy.context import StrategyContext


# ── Fixtures ─────────────────────────────────────────────────────────

EXP = date(2025, 6, 20)
EXP_NEAR = date(2025, 5, 16)
EXP_FAR = date(2025, 6, 20)


@pytest.fixture
def builder():
    return OptionsStrategyBuilder()


@pytest.fixture
def validator():
    return StrategyValidator()


# ══════════════════════════════════════════════════════════════════════
# 1. Strategy Dataclass Defaults
# ══════════════════════════════════════════════════════════════════════


class TestStrategyParams:
    def test_vertical_spread_defaults(self):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        assert p.quantity == Decimal("1")
        assert p.underlying == "AAPL"

    def test_iron_condor_defaults(self):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
        )
        assert p.quantity == Decimal("1")

    def test_straddle_defaults(self):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"))
        assert p.side == "long"
        assert p.quantity == Decimal("1")

    def test_strangle_defaults(self):
        p = StrangleParams(underlying="TSLA", expiration=EXP, put_strike=Decimal("240"), call_strike=Decimal("260"))
        assert p.side == "long"

    def test_butterfly_defaults(self):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("210"),
            contract_type=ContractType.CALL,
        )
        assert p.quantity == Decimal("1")

    def test_calendar_defaults(self):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_NEAR, expiration_far=EXP_FAR,
            strike=Decimal("200"), contract_type=ContractType.CALL,
        )
        assert p.quantity == Decimal("1")

    def test_strategy_analysis_valid(self):
        a = StrategyAnalysis(max_profit=Decimal("500"), max_loss=Decimal("200"))
        assert a.is_valid
        assert a.errors == []

    def test_strategy_analysis_invalid(self):
        a = StrategyAnalysis(errors=["bad strike order"])
        assert not a.is_valid

    def test_frozen_dataclass(self):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        with pytest.raises(AttributeError):
            p.underlying = "TSLA"  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════
# 2. Validator — Parameter Validation
# ══════════════════════════════════════════════════════════════════════


class TestValidatorVerticalSpread:
    def test_valid_bull_call(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        a = validator.validate_vertical_spread(p)
        assert a.is_valid
        assert a.max_profit is not None
        assert a.max_loss is not None

    def test_valid_bear_put(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("200"), short_strike=Decimal("190"),
            contract_type=ContractType.PUT,
        )
        a = validator.validate_vertical_spread(p)
        assert a.is_valid

    def test_valid_bear_call(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("200"), short_strike=Decimal("190"),
            contract_type=ContractType.CALL,
        )
        a = validator.validate_vertical_spread(p)
        assert a.is_valid

    def test_valid_bull_put(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.PUT,
        )
        a = validator.validate_vertical_spread(p)
        assert a.is_valid

    def test_same_strikes_invalid(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("200"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        a = validator.validate_vertical_spread(p)
        assert not a.is_valid
        assert "long_strike and short_strike must differ" in a.errors[0]

    def test_zero_quantity_invalid(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL, quantity=Decimal("0"),
        )
        a = validator.validate_vertical_spread(p)
        assert not a.is_valid
        assert "quantity must be positive" in a.errors[0]

    def test_negative_quantity_invalid(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL, quantity=Decimal("-1"),
        )
        a = validator.validate_vertical_spread(p)
        assert not a.is_valid


class TestValidatorIronCondor:
    def test_valid_iron_condor(self, validator):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
        )
        a = validator.validate_iron_condor(p)
        assert a.is_valid
        assert len(a.breakevens) == 2
        assert a.breakevens[0] == Decimal("410")  # put short strike
        assert a.breakevens[1] == Decimal("440")  # call short strike

    def test_put_strikes_wrong_order(self, validator):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("420"), put_short_strike=Decimal("410"),  # wrong
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
        )
        a = validator.validate_iron_condor(p)
        assert not a.is_valid
        assert "put_long_strike must be less than put_short_strike" in a.errors[0]

    def test_call_strikes_wrong_order(self, validator):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("460"), call_long_strike=Decimal("450"),  # wrong
        )
        a = validator.validate_iron_condor(p)
        assert not a.is_valid
        assert "call_short_strike must be less than call_long_strike" in a.errors[0]

    def test_put_short_above_call_short(self, validator):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("450"),  # crosses call
            call_short_strike=Decimal("440"), call_long_strike=Decimal("460"),
        )
        a = validator.validate_iron_condor(p)
        assert not a.is_valid
        assert "put_short_strike must be less than call_short_strike" in a.errors[0]


class TestValidatorStraddle:
    def test_valid_long_straddle(self, validator):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"), side="long")
        a = validator.validate_straddle(p)
        assert a.is_valid
        assert a.breakevens == [Decimal("250")]

    def test_valid_short_straddle(self, validator):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"), side="short")
        a = validator.validate_straddle(p)
        assert a.is_valid

    def test_invalid_side(self, validator):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"), side="neutral")
        a = validator.validate_straddle(p)
        assert not a.is_valid
        assert "side must be" in a.errors[0]


class TestValidatorStrangle:
    def test_valid_long_strangle(self, validator):
        p = StrangleParams(underlying="TSLA", expiration=EXP, put_strike=Decimal("240"), call_strike=Decimal("260"), side="long")
        a = validator.validate_strangle(p)
        assert a.is_valid
        assert len(a.breakevens) == 2

    def test_valid_short_strangle(self, validator):
        p = StrangleParams(underlying="TSLA", expiration=EXP, put_strike=Decimal("240"), call_strike=Decimal("260"), side="short")
        a = validator.validate_strangle(p)
        assert a.is_valid

    def test_put_above_call_invalid(self, validator):
        p = StrangleParams(underlying="TSLA", expiration=EXP, put_strike=Decimal("270"), call_strike=Decimal("260"), side="long")
        a = validator.validate_strangle(p)
        assert not a.is_valid
        assert "put_strike must be less than call_strike" in a.errors[0]

    def test_same_strikes_invalid(self, validator):
        p = StrangleParams(underlying="TSLA", expiration=EXP, put_strike=Decimal("250"), call_strike=Decimal("250"), side="long")
        a = validator.validate_strangle(p)
        assert not a.is_valid

    def test_invalid_side(self, validator):
        p = StrangleParams(underlying="TSLA", expiration=EXP, put_strike=Decimal("240"), call_strike=Decimal("260"), side="bad")
        a = validator.validate_strangle(p)
        assert not a.is_valid


class TestValidatorButterfly:
    def test_valid_butterfly(self, validator):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("210"),
            contract_type=ContractType.CALL,
        )
        a = validator.validate_butterfly_spread(p)
        assert a.is_valid
        assert len(a.breakevens) == 2
        assert a.breakevens[0] == Decimal("190")
        assert a.breakevens[1] == Decimal("210")

    def test_strikes_wrong_order(self, validator):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("200"), middle_strike=Decimal("190"), upper_strike=Decimal("210"),
            contract_type=ContractType.CALL,
        )
        a = validator.validate_butterfly_spread(p)
        assert not a.is_valid
        assert "strikes must be in order" in a.errors[0]

    def test_unequal_wings_invalid(self, validator):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("215"),
            contract_type=ContractType.CALL,
        )
        a = validator.validate_butterfly_spread(p)
        assert not a.is_valid
        assert "wing widths must be equal" in a.errors[0]


class TestValidatorCalendar:
    def test_valid_calendar(self, validator):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_NEAR, expiration_far=EXP_FAR,
            strike=Decimal("200"), contract_type=ContractType.CALL,
        )
        a = validator.validate_calendar_spread(p)
        assert a.is_valid

    def test_near_after_far_invalid(self, validator):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_FAR, expiration_far=EXP_NEAR,
            strike=Decimal("200"), contract_type=ContractType.CALL,
        )
        a = validator.validate_calendar_spread(p)
        assert not a.is_valid
        assert "expiration_near must be before expiration_far" in a.errors[0]

    def test_same_expiration_invalid(self, validator):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP, expiration_far=EXP,
            strike=Decimal("200"), contract_type=ContractType.CALL,
        )
        a = validator.validate_calendar_spread(p)
        assert not a.is_valid


class TestValidatorMultilegOrder:
    def test_valid_multileg(self, validator):
        legs = [
            Order(
                symbol="AAPL250620C00200000", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("200"),
                expiration_date=EXP, underlying_symbol="AAPL",
            ),
            Order(
                symbol="AAPL250620C00210000", side=OrderSide.SELL, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("210"),
                expiration_date=EXP, underlying_symbol="AAPL",
            ),
        ]
        mlo = MultiLegOrder(id="test", legs=legs, strategy_type="vertical_spread")
        a = validator.validate_multileg_order(mlo)
        assert a.is_valid

    def test_mixed_underlyings_invalid(self, validator):
        legs = [
            Order(
                symbol="AAPL250620C00200000", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("200"),
                expiration_date=EXP, underlying_symbol="AAPL",
            ),
            Order(
                symbol="TSLA250620C00250000", side=OrderSide.SELL, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("250"),
                expiration_date=EXP, underlying_symbol="TSLA",
            ),
        ]
        mlo = MultiLegOrder(id="test", legs=legs, strategy_type="vertical_spread")
        a = validator.validate_multileg_order(mlo)
        assert not a.is_valid
        assert "same underlying" in a.errors[0]

    def test_mixed_expirations_non_calendar_invalid(self, validator):
        legs = [
            Order(
                symbol="AAPL250516C00200000", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("200"),
                expiration_date=EXP_NEAR, underlying_symbol="AAPL",
            ),
            Order(
                symbol="AAPL250620C00210000", side=OrderSide.SELL, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("210"),
                expiration_date=EXP_FAR, underlying_symbol="AAPL",
            ),
        ]
        mlo = MultiLegOrder(id="test", legs=legs, strategy_type="vertical_spread")
        a = validator.validate_multileg_order(mlo)
        assert not a.is_valid
        assert "same expiration" in a.errors[0]

    def test_calendar_spread_different_expirations_valid(self, validator):
        legs = [
            Order(
                symbol="AAPL250516C00200000", side=OrderSide.SELL, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("200"),
                expiration_date=EXP_NEAR, underlying_symbol="AAPL",
            ),
            Order(
                symbol="AAPL250620C00200000", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=Decimal("1"), asset_class=AssetClass.OPTION,
                contract_type=ContractType.CALL, strike_price=Decimal("200"),
                expiration_date=EXP_FAR, underlying_symbol="AAPL",
            ),
        ]
        mlo = MultiLegOrder(id="test", legs=legs, strategy_type="calendar_spread")
        a = validator.validate_multileg_order(mlo)
        assert a.is_valid

    def test_empty_legs_invalid(self, validator):
        # MultiLegOrder itself requires at least one leg
        with pytest.raises(ValueError, match="at least one leg"):
            MultiLegOrder(id="test", legs=[], strategy_type="vertical_spread")


# ══════════════════════════════════════════════════════════════════════
# 3. Strategy Builder — Build Methods
# ══════════════════════════════════════════════════════════════════════


class TestBuildVerticalSpread:
    def test_bull_call_spread(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL, quantity=Decimal("5"),
        )
        mlo = builder.build_vertical_spread(p)
        assert isinstance(mlo, MultiLegOrder)
        assert mlo.strategy_type == "vertical_spread"
        assert len(mlo.legs) == 2

        buy_leg = [l for l in mlo.legs if l.side == OrderSide.BUY][0]
        sell_leg = [l for l in mlo.legs if l.side == OrderSide.SELL][0]
        assert buy_leg.strike_price == Decimal("190")
        assert sell_leg.strike_price == Decimal("200")
        assert buy_leg.contract_type == ContractType.CALL
        assert sell_leg.contract_type == ContractType.CALL
        assert buy_leg.quantity == Decimal("5")
        assert sell_leg.quantity == Decimal("5")
        assert buy_leg.underlying_symbol == "AAPL"
        assert sell_leg.underlying_symbol == "AAPL"
        assert buy_leg.asset_class == AssetClass.OPTION
        assert sell_leg.expiration_date == EXP

    def test_bear_put_spread(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("200"), short_strike=Decimal("190"),
            contract_type=ContractType.PUT,
        )
        mlo = builder.build_vertical_spread(p)
        buy_leg = [l for l in mlo.legs if l.side == OrderSide.BUY][0]
        sell_leg = [l for l in mlo.legs if l.side == OrderSide.SELL][0]
        assert buy_leg.strike_price == Decimal("200")
        assert sell_leg.strike_price == Decimal("190")
        assert buy_leg.contract_type == ContractType.PUT

    def test_bear_call_spread(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("210"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        mlo = builder.build_vertical_spread(p)
        buy_leg = [l for l in mlo.legs if l.side == OrderSide.BUY][0]
        sell_leg = [l for l in mlo.legs if l.side == OrderSide.SELL][0]
        assert buy_leg.strike_price == Decimal("210")
        assert sell_leg.strike_price == Decimal("200")

    def test_bull_put_spread(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.PUT,
        )
        mlo = builder.build_vertical_spread(p)
        assert len(mlo.legs) == 2

    def test_invalid_same_strikes_raises(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("200"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        with pytest.raises(StrategyValidationError, match="must differ"):
            builder.build_vertical_spread(p)

    def test_option_symbol_format(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        mlo = builder.build_vertical_spread(p)
        buy_leg = [l for l in mlo.legs if l.side == OrderSide.BUY][0]
        assert buy_leg.option_symbol == "AAPL250620C00190000"
        sell_leg = [l for l in mlo.legs if l.side == OrderSide.SELL][0]
        assert sell_leg.option_symbol == "AAPL250620C00200000"


class TestBuildIronCondor:
    def test_valid_iron_condor(self, builder):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
            quantity=Decimal("2"),
        )
        mlo = builder.build_iron_condor(p)
        assert mlo.strategy_type == "iron_condor"
        assert len(mlo.legs) == 4

        # Check legs
        put_legs = [l for l in mlo.legs if l.contract_type == ContractType.PUT]
        call_legs = [l for l in mlo.legs if l.contract_type == ContractType.CALL]
        assert len(put_legs) == 2
        assert len(call_legs) == 2

        put_buy = [l for l in put_legs if l.side == OrderSide.BUY][0]
        put_sell = [l for l in put_legs if l.side == OrderSide.SELL][0]
        assert put_buy.strike_price == Decimal("400")
        assert put_sell.strike_price == Decimal("410")

        call_buy = [l for l in call_legs if l.side == OrderSide.BUY][0]
        call_sell = [l for l in call_legs if l.side == OrderSide.SELL][0]
        assert call_sell.strike_price == Decimal("440")
        assert call_buy.strike_price == Decimal("450")

        # All legs have same underlying and expiration
        for leg in mlo.legs:
            assert leg.underlying_symbol == "SPY"
            assert leg.expiration_date == EXP
            assert leg.quantity == Decimal("2")

    def test_invalid_strike_order_raises(self, builder):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("420"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
        )
        with pytest.raises(StrategyValidationError):
            builder.build_iron_condor(p)


class TestBuildStraddle:
    def test_long_straddle(self, builder):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"), quantity=Decimal("3"), side="long")
        mlo = builder.build_straddle(p)
        assert mlo.strategy_type == "straddle"
        assert len(mlo.legs) == 2

        call_leg = [l for l in mlo.legs if l.contract_type == ContractType.CALL][0]
        put_leg = [l for l in mlo.legs if l.contract_type == ContractType.PUT][0]
        assert call_leg.side == OrderSide.BUY
        assert put_leg.side == OrderSide.BUY
        assert call_leg.strike_price == Decimal("250")
        assert put_leg.strike_price == Decimal("250")
        assert call_leg.quantity == Decimal("3")

    def test_short_straddle(self, builder):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"), side="short")
        mlo = builder.build_straddle(p)
        call_leg = [l for l in mlo.legs if l.contract_type == ContractType.CALL][0]
        put_leg = [l for l in mlo.legs if l.contract_type == ContractType.PUT][0]
        assert call_leg.side == OrderSide.SELL
        assert put_leg.side == OrderSide.SELL

    def test_invalid_side_raises(self, builder):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"), side="neutral")
        with pytest.raises(StrategyValidationError, match="side must be"):
            builder.build_straddle(p)


class TestBuildStrangle:
    def test_long_strangle(self, builder):
        p = StrangleParams(
            underlying="TSLA", expiration=EXP,
            put_strike=Decimal("240"), call_strike=Decimal("260"),
            quantity=Decimal("2"), side="long",
        )
        mlo = builder.build_strangle(p)
        assert mlo.strategy_type == "strangle"
        assert len(mlo.legs) == 2

        put_leg = [l for l in mlo.legs if l.contract_type == ContractType.PUT][0]
        call_leg = [l for l in mlo.legs if l.contract_type == ContractType.CALL][0]
        assert put_leg.side == OrderSide.BUY
        assert call_leg.side == OrderSide.BUY
        assert put_leg.strike_price == Decimal("240")
        assert call_leg.strike_price == Decimal("260")

    def test_short_strangle(self, builder):
        p = StrangleParams(
            underlying="TSLA", expiration=EXP,
            put_strike=Decimal("240"), call_strike=Decimal("260"), side="short",
        )
        mlo = builder.build_strangle(p)
        put_leg = [l for l in mlo.legs if l.contract_type == ContractType.PUT][0]
        call_leg = [l for l in mlo.legs if l.contract_type == ContractType.CALL][0]
        assert put_leg.side == OrderSide.SELL
        assert call_leg.side == OrderSide.SELL

    def test_invalid_put_above_call_raises(self, builder):
        p = StrangleParams(
            underlying="TSLA", expiration=EXP,
            put_strike=Decimal("270"), call_strike=Decimal("260"), side="long",
        )
        with pytest.raises(StrategyValidationError, match="put_strike must be less"):
            builder.build_strangle(p)


class TestBuildButterfly:
    def test_call_butterfly(self, builder):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("210"),
            contract_type=ContractType.CALL, quantity=Decimal("1"),
        )
        mlo = builder.build_butterfly_spread(p)
        assert mlo.strategy_type == "butterfly_spread"
        assert len(mlo.legs) == 3

        buy_legs = [l for l in mlo.legs if l.side == OrderSide.BUY]
        sell_legs = [l for l in mlo.legs if l.side == OrderSide.SELL]
        assert len(buy_legs) == 2  # lower and upper wings
        assert len(sell_legs) == 1  # middle (2x quantity)
        assert sell_legs[0].strike_price == Decimal("200")
        assert sell_legs[0].quantity == Decimal("2")

        buy_strikes = sorted(l.strike_price for l in buy_legs)
        assert buy_strikes == [Decimal("190"), Decimal("210")]

    def test_put_butterfly(self, builder):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("210"),
            contract_type=ContractType.PUT,
        )
        mlo = builder.build_butterfly_spread(p)
        for leg in mlo.legs:
            assert leg.contract_type == ContractType.PUT

    def test_unequal_wings_raises(self, builder):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("215"),
            contract_type=ContractType.CALL,
        )
        with pytest.raises(StrategyValidationError, match="wing widths must be equal"):
            builder.build_butterfly_spread(p)

    def test_wrong_strike_order_raises(self, builder):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("210"), middle_strike=Decimal("200"), upper_strike=Decimal("190"),
            contract_type=ContractType.CALL,
        )
        with pytest.raises(StrategyValidationError, match="strikes must be in order"):
            builder.build_butterfly_spread(p)


class TestBuildCalendarSpread:
    def test_valid_call_calendar(self, builder):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_NEAR, expiration_far=EXP_FAR,
            strike=Decimal("200"), contract_type=ContractType.CALL, quantity=Decimal("3"),
        )
        mlo = builder.build_calendar_spread(p)
        assert mlo.strategy_type == "calendar_spread"
        assert len(mlo.legs) == 2

        sell_leg = [l for l in mlo.legs if l.side == OrderSide.SELL][0]
        buy_leg = [l for l in mlo.legs if l.side == OrderSide.BUY][0]
        assert sell_leg.expiration_date == EXP_NEAR
        assert buy_leg.expiration_date == EXP_FAR
        assert sell_leg.strike_price == Decimal("200")
        assert buy_leg.strike_price == Decimal("200")
        assert sell_leg.quantity == Decimal("3")

    def test_valid_put_calendar(self, builder):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_NEAR, expiration_far=EXP_FAR,
            strike=Decimal("200"), contract_type=ContractType.PUT,
        )
        mlo = builder.build_calendar_spread(p)
        for leg in mlo.legs:
            assert leg.contract_type == ContractType.PUT

    def test_near_after_far_raises(self, builder):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_FAR, expiration_far=EXP_NEAR,
            strike=Decimal("200"), contract_type=ContractType.CALL,
        )
        with pytest.raises(StrategyValidationError, match="expiration_near must be before"):
            builder.build_calendar_spread(p)


# ══════════════════════════════════════════════════════════════════════
# 4. Strategy Builder — All legs share common properties
# ══════════════════════════════════════════════════════════════════════


class TestLegProperties:
    """Verify all legs built by the builder have correct common fields."""

    def test_all_legs_are_option_asset_class(self, builder):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
        )
        mlo = builder.build_iron_condor(p)
        for leg in mlo.legs:
            assert leg.asset_class == AssetClass.OPTION

    def test_all_legs_have_order_ids(self, builder):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"))
        mlo = builder.build_straddle(p)
        ids = {leg.order_id for leg in mlo.legs}
        assert len(ids) == 2  # unique IDs
        assert "" not in ids

    def test_multileg_has_id(self, builder):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"))
        mlo = builder.build_straddle(p)
        assert mlo.id != ""

    def test_all_legs_limit_order_type(self, builder):
        p = StrangleParams(
            underlying="TSLA", expiration=EXP,
            put_strike=Decimal("240"), call_strike=Decimal("260"),
        )
        mlo = builder.build_strangle(p)
        for leg in mlo.legs:
            assert leg.order_type == OrderType.LIMIT


# ══════════════════════════════════════════════════════════════════════
# 5. Max Profit / Max Loss / Breakeven Calculations
# ══════════════════════════════════════════════════════════════════════


class TestRiskRewardAnalysis:
    def test_vertical_spread_analysis(self, validator):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL, quantity=Decimal("2"),
        )
        a = validator.validate_vertical_spread(p)
        assert a.is_valid
        # Width = 10, multiplier = 100, quantity = 2 → 2000
        assert a.max_profit == Decimal("2000")
        assert a.max_loss == Decimal("2000")
        assert a.breakevens == [Decimal("190")]

    def test_iron_condor_analysis(self, validator):
        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
            quantity=Decimal("1"),
        )
        a = validator.validate_iron_condor(p)
        assert a.is_valid
        # Both wings = 10 wide, so max_loss = 10 * 100 * 1 = 1000
        assert a.max_loss == Decimal("1000")
        assert len(a.breakevens) == 2

    def test_butterfly_analysis(self, validator):
        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("210"),
            contract_type=ContractType.CALL, quantity=Decimal("1"),
        )
        a = validator.validate_butterfly_spread(p)
        assert a.is_valid
        # Wing width = 10, multiplier = 100 → 1000
        assert a.max_profit == Decimal("1000")
        assert a.max_loss == Decimal("1000")
        assert a.breakevens == [Decimal("190"), Decimal("210")]

    def test_straddle_analysis_long(self, validator):
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"), side="long")
        a = validator.validate_straddle(p)
        assert a.is_valid
        # Long straddle: unlimited profit, loss = premium (unknown)
        assert a.max_profit is None
        assert a.max_loss is None
        assert a.breakevens == [Decimal("250")]

    def test_strangle_analysis_short(self, validator):
        p = StrangleParams(
            underlying="TSLA", expiration=EXP,
            put_strike=Decimal("240"), call_strike=Decimal("260"), side="short",
        )
        a = validator.validate_strangle(p)
        assert a.is_valid
        assert a.breakevens == [Decimal("240"), Decimal("260")]

    def test_calendar_analysis_indeterminate(self, validator):
        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_NEAR, expiration_far=EXP_FAR,
            strike=Decimal("200"), contract_type=ContractType.CALL,
        )
        a = validator.validate_calendar_spread(p)
        assert a.is_valid
        # Calendar P/L depends on IV — indeterminate
        assert a.max_profit is None
        assert a.max_loss is None


# ══════════════════════════════════════════════════════════════════════
# 6. Build and Submit Flow
# ══════════════════════════════════════════════════════════════════════


class TestBuildAndSubmit:
    async def test_build_and_submit_vertical(self, builder):
        router = AsyncMock()
        router.submit_multileg_order = AsyncMock(return_value=None)

        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        mlo = await builder.build_and_submit(p, router)
        assert isinstance(mlo, MultiLegOrder)
        assert mlo.strategy_type == "vertical_spread"
        router.submit_multileg_order.assert_awaited_once_with(mlo)

    async def test_build_and_submit_iron_condor(self, builder):
        router = AsyncMock()
        router.submit_multileg_order = AsyncMock(return_value=None)

        p = IronCondorParams(
            underlying="SPY", expiration=EXP,
            put_long_strike=Decimal("400"), put_short_strike=Decimal("410"),
            call_short_strike=Decimal("440"), call_long_strike=Decimal("450"),
        )
        mlo = await builder.build_and_submit(p, router)
        assert len(mlo.legs) == 4
        router.submit_multileg_order.assert_awaited_once()

    async def test_build_and_submit_straddle(self, builder):
        router = AsyncMock()
        router.submit_multileg_order = AsyncMock(return_value=None)

        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"))
        mlo = await builder.build_and_submit(p, router)
        assert mlo.strategy_type == "straddle"
        router.submit_multileg_order.assert_awaited_once()

    async def test_build_and_submit_strangle(self, builder):
        router = AsyncMock()
        router.submit_multileg_order = AsyncMock(return_value=None)

        p = StrangleParams(underlying="TSLA", expiration=EXP, put_strike=Decimal("240"), call_strike=Decimal("260"))
        mlo = await builder.build_and_submit(p, router)
        assert mlo.strategy_type == "strangle"

    async def test_build_and_submit_butterfly(self, builder):
        router = AsyncMock()
        router.submit_multileg_order = AsyncMock(return_value=None)

        p = ButterflySpreadParams(
            underlying="AAPL", expiration=EXP,
            lower_strike=Decimal("190"), middle_strike=Decimal("200"), upper_strike=Decimal("210"),
            contract_type=ContractType.CALL,
        )
        mlo = await builder.build_and_submit(p, router)
        assert mlo.strategy_type == "butterfly_spread"

    async def test_build_and_submit_calendar(self, builder):
        router = AsyncMock()
        router.submit_multileg_order = AsyncMock(return_value=None)

        p = CalendarSpreadParams(
            underlying="AAPL", expiration_near=EXP_NEAR, expiration_far=EXP_FAR,
            strike=Decimal("200"), contract_type=ContractType.CALL,
        )
        mlo = await builder.build_and_submit(p, router)
        assert mlo.strategy_type == "calendar_spread"

    async def test_build_and_submit_invalid_raises(self, builder):
        router = AsyncMock()
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("200"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        with pytest.raises(StrategyValidationError):
            await builder.build_and_submit(p, router)
        router.submit_multileg_order.assert_not_awaited()

    async def test_build_and_submit_unknown_type_raises(self, builder):
        router = AsyncMock()
        with pytest.raises(TypeError, match="Unknown strategy params type"):
            await builder.build_and_submit("not a strategy", router)


# ══════════════════════════════════════════════════════════════════════
# 7. StrategyContext Integration
# ══════════════════════════════════════════════════════════════════════


class TestStrategyContextIntegration:
    def test_context_has_options_builder(self):
        bus = EventBus()
        osb = OptionsStrategyBuilder()
        ctx = StrategyContext(
            strategy_id="test",
            event_bus=bus,
            options_strategy_builder=osb,
        )
        assert ctx.options_strategy_builder is osb

    def test_context_no_builder_returns_none(self):
        bus = EventBus()
        ctx = StrategyContext(strategy_id="test", event_bus=bus)
        assert ctx.options_strategy_builder is None

    async def test_submit_options_strategy(self):
        bus = EventBus()
        mock_exec = AsyncMock()
        mock_exec.submit_multileg_order = AsyncMock(return_value=None)
        osb = OptionsStrategyBuilder()
        ctx = StrategyContext(
            strategy_id="test",
            event_bus=bus,
            exec_adapter=mock_exec,
            options_strategy_builder=osb,
        )

        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL,
        )
        result = await ctx.submit_options_strategy(p)
        assert isinstance(result, MultiLegOrder)
        mock_exec.submit_multileg_order.assert_awaited_once()

    async def test_submit_options_strategy_no_builder(self):
        bus = EventBus()
        ctx = StrategyContext(strategy_id="test", event_bus=bus)
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"))
        result = await ctx.submit_options_strategy(p)
        assert result is None

    async def test_submit_options_strategy_no_exec(self):
        bus = EventBus()
        osb = OptionsStrategyBuilder()
        ctx = StrategyContext(
            strategy_id="test",
            event_bus=bus,
            options_strategy_builder=osb,
        )
        p = StraddleParams(underlying="TSLA", expiration=EXP, strike=Decimal("250"))
        result = await ctx.submit_options_strategy(p)
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# 8. StrategyManager passes builder to context
# ══════════════════════════════════════════════════════════════════════


class TestStrategyManagerBuilder:
    def test_manager_passes_builder_to_context(self):
        from trading_platform.strategy.base import Strategy
        from trading_platform.strategy.manager import StrategyManager

        bus = EventBus()
        osb = OptionsStrategyBuilder()
        mgr = StrategyManager(
            event_bus=bus,
            options_strategy_builder=osb,
        )

        class DummyStrategy(Strategy):
            async def on_quote(self, quote): pass
            async def on_trade(self, trade): pass
            async def on_bar(self, bar): pass

        strat = DummyStrategy(name="dummy", event_bus=bus, config={})
        mgr.register(strat)
        assert strat.context.options_strategy_builder is osb

    def test_manager_no_builder(self):
        from trading_platform.strategy.base import Strategy
        from trading_platform.strategy.manager import StrategyManager

        bus = EventBus()
        mgr = StrategyManager(event_bus=bus)

        class DummyStrategy(Strategy):
            async def on_quote(self, quote): pass
            async def on_trade(self, trade): pass
            async def on_bar(self, bar): pass

        strat = DummyStrategy(name="dummy", event_bus=bus, config={})
        mgr.register(strat)
        assert strat.context.options_strategy_builder is None


# ══════════════════════════════════════════════════════════════════════
# 9. StrategyValidationError
# ══════════════════════════════════════════════════════════════════════


class TestStrategyValidationError:
    def test_error_stores_errors(self):
        err = StrategyValidationError(["bad strike", "bad qty"])
        assert err.errors == ["bad strike", "bad qty"]
        assert "bad strike" in str(err)
        assert "bad qty" in str(err)

    def test_error_single(self):
        err = StrategyValidationError(["oops"])
        assert str(err) == "oops"


# ══════════════════════════════════════════════════════════════════════
# 10. Edge Cases
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_large_quantity(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL, quantity=Decimal("1000"),
        )
        mlo = builder.build_vertical_spread(p)
        for leg in mlo.legs:
            assert leg.quantity == Decimal("1000")

    def test_fractional_quantity(self, builder):
        """Even though options are typically whole numbers, Decimal supports it."""
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.CALL, quantity=Decimal("0.5"),
        )
        mlo = builder.build_vertical_spread(p)
        for leg in mlo.legs:
            assert leg.quantity == Decimal("0.5")

    def test_wide_strikes(self, builder):
        p = VerticalSpreadParams(
            underlying="AMZN", expiration=EXP,
            long_strike=Decimal("100"), short_strike=Decimal("300"),
            contract_type=ContractType.CALL,
        )
        mlo = builder.build_vertical_spread(p)
        assert len(mlo.legs) == 2

    def test_put_option_symbol_format(self, builder):
        p = VerticalSpreadParams(
            underlying="AAPL", expiration=EXP,
            long_strike=Decimal("190"), short_strike=Decimal("200"),
            contract_type=ContractType.PUT,
        )
        mlo = builder.build_vertical_spread(p)
        buy_leg = [l for l in mlo.legs if l.side == OrderSide.BUY][0]
        assert "P" in buy_leg.option_symbol
        assert buy_leg.option_symbol == "AAPL250620P00190000"
