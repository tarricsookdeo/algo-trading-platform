"""Risk-related models and configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RiskConfig(BaseModel):
    """Risk management configuration."""

    max_position_size: float = 1000.0
    max_position_concentration: float = 0.10
    max_order_value: float = 50000.0
    daily_loss_limit: float = -5000.0
    max_open_orders: int = 20
    max_daily_trades: int = 100
    max_portfolio_drawdown: float = 0.15
    allowed_symbols: list[str] = Field(default_factory=list)
    blocked_symbols: list[str] = Field(default_factory=list)


class RiskViolation(BaseModel):
    """Record of a risk check violation."""

    check_name: str
    message: str
    order_id: str = ""
    symbol: str = ""
    timestamp: datetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class RiskState(BaseModel):
    """Current risk state snapshot."""

    is_halted: bool = False
    halt_reason: str = ""
    daily_pnl: float = 0.0
    daily_trade_count: int = 0
    portfolio_peak: float = 0.0
    portfolio_value: float = 0.0
    open_order_count: int = 0
    violations: list[RiskViolation] = Field(default_factory=list)
