"""Convert between Public.com SDK models and platform domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trading_platform.core.enums import AssetClass, OrderSide, OrderStatus, OrderType
from trading_platform.core.models import Fill, Order, Position


# ── OrderStatus mapping ──────────────────────────────────────────────

_STATUS_MAP: dict[str, OrderStatus] = {
    "NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELED,
    "CANCELED": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "PENDING_NEW": OrderStatus.PENDING_NEW,
    "PENDING_CANCEL": OrderStatus.PENDING_CANCEL,
    "EXPIRED": OrderStatus.EXPIRED,
    "REPLACED": OrderStatus.CANCELED,
}

_SIDE_MAP: dict[str, OrderSide] = {
    "BUY": OrderSide.BUY,
    "SELL": OrderSide.SELL,
}

_TYPE_MAP: dict[str, OrderType] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP": OrderType.STOP,
    "STOP_LIMIT": OrderType.STOP_LIMIT,
}


def map_order_status(sdk_status: Any) -> OrderStatus:
    """Map SDK OrderStatus enum to platform OrderStatus."""
    name = str(sdk_status.name) if hasattr(sdk_status, "name") else str(sdk_status)
    return _STATUS_MAP.get(name.upper(), OrderStatus.NEW)


def sdk_order_to_platform(sdk_order: Any) -> Order:
    """Convert an SDK Order object to a platform Order model."""
    status = map_order_status(sdk_order.status) if hasattr(sdk_order, "status") else OrderStatus.NEW

    side_val = OrderSide.BUY
    if hasattr(sdk_order, "order_side") and sdk_order.order_side:
        side_name = str(sdk_order.order_side.name) if hasattr(sdk_order.order_side, "name") else str(sdk_order.order_side)
        side_val = _SIDE_MAP.get(side_name.upper(), OrderSide.BUY)

    type_val = OrderType.MARKET
    if hasattr(sdk_order, "order_type") and sdk_order.order_type:
        type_name = str(sdk_order.order_type.name) if hasattr(sdk_order.order_type, "name") else str(sdk_order.order_type)
        type_val = _TYPE_MAP.get(type_name.upper(), OrderType.MARKET)

    symbol = ""
    if hasattr(sdk_order, "instrument") and sdk_order.instrument:
        symbol = getattr(sdk_order.instrument, "symbol", "")

    quantity = float(getattr(sdk_order, "quantity", 0) or 0)
    limit_price = float(getattr(sdk_order, "limit_price", 0) or 0) or None
    stop_price = float(getattr(sdk_order, "stop_price", 0) or 0) or None
    filled_qty = float(getattr(sdk_order, "filled_quantity", 0) or 0)
    filled_avg = float(getattr(sdk_order, "average_fill_price", 0) or 0)

    return Order(
        order_id=getattr(sdk_order, "order_id", ""),
        symbol=symbol,
        side=side_val,
        order_type=type_val,
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        status=status,
        filled_quantity=filled_qty,
        filled_avg_price=filled_avg,
        created_at=getattr(sdk_order, "created_at", None),
        updated_at=getattr(sdk_order, "updated_at", None),
    )


def sdk_position_to_platform(sdk_pos: Any) -> Position:
    """Convert an SDK PortfolioPosition to a platform Position."""
    symbol = getattr(sdk_pos, "symbol", "")
    quantity = float(getattr(sdk_pos, "quantity", 0) or 0)
    avg_entry = float(getattr(sdk_pos, "average_price", 0) or 0)
    market_value = float(getattr(sdk_pos, "market_value", 0) or 0)
    unrealized = float(getattr(sdk_pos, "unrealized_pnl", 0) or 0)
    side = "long" if quantity >= 0 else "short"

    return Position(
        symbol=symbol,
        quantity=abs(quantity),
        avg_entry_price=avg_entry,
        market_value=market_value,
        unrealized_pnl=unrealized,
        side=side,
    )
