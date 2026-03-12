"""Domain models for the trading platform.

All models are provider-agnostic — strategies and core logic import these,
never adapter-specific types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from trading_platform.core.enums import AssetClass, BarType, OrderSide, OrderStatus, OrderType


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
    asset_class: AssetClass = AssetClass.STOCK
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
    quantity: float = 0.0
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    filled_avg_price: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Fill(BaseModel):
    """Trade fill (placeholder for execution layer)."""
    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    price: float = 0.0
    quantity: float = 0.0
    timestamp: datetime | None = None


class Position(BaseModel):
    """Current position (placeholder for execution layer)."""
    symbol: str = ""
    quantity: float = 0.0
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
