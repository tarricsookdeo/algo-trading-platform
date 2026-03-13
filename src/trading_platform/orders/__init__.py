"""Advanced order types: trailing stops, scaled entries/exits."""

from trading_platform.orders.trailing_stop import TrailingStopManager
from trading_platform.orders.scaled import ScaledOrderManager

__all__ = ["TrailingStopManager", "ScaledOrderManager"]
