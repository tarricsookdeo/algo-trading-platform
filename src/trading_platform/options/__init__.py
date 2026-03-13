"""Options strategy builder — constructs, validates, and submits multi-leg options strategies."""

from trading_platform.options.expiration import (
    ExpirationConfig,
    ExpirationManager,
    OptionsPosition,
)
from trading_platform.options.greeks import AggregatedGreeks, GreeksData, GreeksProvider
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

__all__ = [
    "AggregatedGreeks",
    "ButterflySpreadParams",
    "CalendarSpreadParams",
    "ExpirationConfig",
    "ExpirationManager",
    "GreeksData",
    "GreeksProvider",
    "IronCondorParams",
    "OptionsPosition",
    "OptionsStrategyBuilder",
    "StraddleParams",
    "StrangleParams",
    "StrategyAnalysis",
    "StrategyValidationError",
    "StrategyValidator",
    "VerticalSpreadParams",
]
