"""Strategy parameter dataclasses and analysis results for multi-leg options strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from trading_platform.core.enums import ContractType


@dataclass(frozen=True)
class VerticalSpreadParams:
    """Parameters for a vertical (bull/bear) spread."""

    underlying: str
    expiration: date
    long_strike: Decimal
    short_strike: Decimal
    contract_type: ContractType
    quantity: Decimal = Decimal("1")


@dataclass(frozen=True)
class IronCondorParams:
    """Parameters for an iron condor."""

    underlying: str
    expiration: date
    put_long_strike: Decimal
    put_short_strike: Decimal
    call_short_strike: Decimal
    call_long_strike: Decimal
    quantity: Decimal = Decimal("1")


@dataclass(frozen=True)
class StraddleParams:
    """Parameters for a long or short straddle."""

    underlying: str
    expiration: date
    strike: Decimal
    quantity: Decimal = Decimal("1")
    side: str = "long"  # "long" or "short"


@dataclass(frozen=True)
class StrangleParams:
    """Parameters for a long or short strangle."""

    underlying: str
    expiration: date
    put_strike: Decimal
    call_strike: Decimal
    quantity: Decimal = Decimal("1")
    side: str = "long"  # "long" or "short"


@dataclass(frozen=True)
class ButterflySpreadParams:
    """Parameters for a butterfly spread."""

    underlying: str
    expiration: date
    lower_strike: Decimal
    middle_strike: Decimal
    upper_strike: Decimal
    contract_type: ContractType
    quantity: Decimal = Decimal("1")


@dataclass(frozen=True)
class CalendarSpreadParams:
    """Parameters for a calendar (time) spread."""

    underlying: str
    expiration_near: date
    expiration_far: date
    strike: Decimal
    contract_type: ContractType
    quantity: Decimal = Decimal("1")


@dataclass
class StrategyAnalysis:
    """Risk/reward analysis produced by the validator."""

    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    breakevens: list[Decimal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0
