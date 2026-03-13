"""Bracket order data model."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field

from trading_platform.bracket.enums import BracketState
from trading_platform.core.enums import OrderType


class BracketOrder(BaseModel):
    """Represents a synthetic bracket order with entry, stop-loss, and take-profit."""

    bracket_id: str
    symbol: str
    quantity: int
    entry_type: OrderType  # MARKET or LIMIT
    entry_limit_price: Decimal | None = None
    stop_loss_price: Decimal
    take_profit_price: Decimal

    # State tracking
    state: BracketState = BracketState.PENDING_ENTRY

    # Child order IDs
    entry_order_id: str | None = None
    stop_loss_order_id: str | None = None
    take_profit_order_id: str | None = None

    # Fill tracking
    entry_fill_price: Decimal | None = None
    exit_fill_price: Decimal | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entry_filled_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"ser_json_timedelta": "float"}
