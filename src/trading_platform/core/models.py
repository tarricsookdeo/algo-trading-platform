"""Domain models for the trading platform.

All models are provider-agnostic — strategies and core logic import these,
never adapter-specific types.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from trading_platform.core.enums import (
    AssetClass,
    BarType,
    ContractType,
    OrderSide,
    OrderStatus,
    OrderType,
)


class QuoteTick(BaseModel):
    """Level 1 quote tick."""
    symbol: str
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float
    bid_exchange: str = ""
    ask_exchange: str = ""
    timestamp: datetime
    conditions: list[str] = Field(default_factory=list)

    model_config = {"ser_json_timedelta": "float"}


class TradeTick(BaseModel):
    """Individual trade tick."""
    symbol: str
    price: float
    size: float
    exchange: str = ""
    trade_id: str = ""
    conditions: list[str] = Field(default_factory=list)
    timestamp: datetime
    tape: str = ""

    model_config = {"ser_json_timedelta": "float"}


class Bar(BaseModel):
    """OHLCV bar."""
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    trade_count: int = 0
    timestamp: datetime
    bar_type: BarType = BarType.MINUTE

    model_config = {"ser_json_timedelta": "float"}


class TradingStatus(BaseModel):
    """Trading status change for a symbol."""
    symbol: str
    status_code: str
    status_message: str
    reason_code: str = ""
    reason_message: str = ""
    timestamp: datetime


class LULD(BaseModel):
    """Limit Up / Limit Down band."""
    symbol: str
    limit_up: float
    limit_down: float
    indicator: str = ""
    timestamp: datetime


class Instrument(BaseModel):
    """Tradable instrument definition."""
    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.EQUITY
    exchange: str = ""
    tradable: bool = True
    shortable: bool = False
    marginable: bool = False
    easy_to_borrow: bool = False
    # Option-specific fields
    strike: float | None = None
    expiry: datetime | None = None
    option_type: str | None = None  # "call" or "put"
    underlying: str | None = None


class Order(BaseModel):
    """Order representation (placeholder for execution layer)."""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal = Decimal("0")
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: Decimal = Decimal("0")
    filled_avg_price: float = 0.0
    asset_class: AssetClass = AssetClass.EQUITY
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Options-specific fields (required when asset_class is OPTION)
    contract_type: ContractType | None = None
    strike_price: Decimal | None = None
    expiration_date: date | None = None
    underlying_symbol: str | None = None
    option_symbol: str | None = None

    @model_validator(mode="after")
    def _validate_option_fields(self) -> Order:
        if self.asset_class == AssetClass.OPTION:
            missing = []
            if self.contract_type is None:
                missing.append("contract_type")
            if self.strike_price is None:
                missing.append("strike_price")
            if self.expiration_date is None:
                missing.append("expiration_date")
            if not self.underlying_symbol:
                missing.append("underlying_symbol")
            if missing:
                raise ValueError(
                    f"Options orders require: {', '.join(missing)}"
                )
        return self


class MultiLegOrder(BaseModel):
    """Multi-leg options order (e.g., spreads, iron condors)."""
    id: str = ""
    legs: list[Order] = Field(default_factory=list)
    strategy_type: str = ""
    net_debit_or_credit: Decimal | None = None
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_legs(self) -> MultiLegOrder:
        if not self.legs:
            raise ValueError("MultiLegOrder requires at least one leg")
        for i, leg in enumerate(self.legs):
            if leg.asset_class != AssetClass.OPTION:
                raise ValueError(
                    f"Leg {i} must have asset_class OPTION, got {leg.asset_class}"
                )
        return self


class Fill(BaseModel):
    """Trade fill (placeholder for execution layer)."""
    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    price: float = 0.0
    quantity: Decimal = Decimal("0")
    timestamp: datetime | None = None


class Position(BaseModel):
    """Current position (placeholder for execution layer)."""
    symbol: str = ""
    quantity: Decimal = Decimal("0")
    avg_entry_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    side: str = ""


class SystemEvent(BaseModel):
    """Internal system event for the event bus."""
    component: str
    message: str
    level: str = "info"
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime | None = None
