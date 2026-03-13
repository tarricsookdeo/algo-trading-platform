"""Trailing stop order manager.

Monitors bid prices and ratchets a resting stop-loss order upward as the
market price rises, using cancel_and_replace for efficient updates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from trading_platform.adapters.base import ExecAdapter
from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Order, QuoteTick


class TrailingStopState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"


TRAILING_STOP_TERMINAL_STATES = frozenset({
    TrailingStopState.COMPLETED,
    TrailingStopState.CANCELED,
    TrailingStopState.ERROR,
})


class TrailingStopChannel(StrEnum):
    TRAILING_STOP_PLACED = "trailing_stop.placed"
    TRAILING_STOP_UPDATED = "trailing_stop.updated"
    TRAILING_STOP_COMPLETED = "trailing_stop.completed"
    TRAILING_STOP_CANCELED = "trailing_stop.canceled"
    TRAILING_STOP_ERROR = "trailing_stop.error"
    TRAILING_STOP_STATE_CHANGE = "trailing_stop.state_change"


@dataclass
class TrailingStop:
    """Tracks state for a single trailing stop."""
    trailing_stop_id: str
    symbol: str
    quantity: Decimal
    trail_amount: Decimal | None = None
    trail_percent: Decimal | None = None
    current_stop_price: Decimal = Decimal("0")
    highest_price: Decimal = Decimal("0")
    stop_order_id: str | None = None
    state: TrailingStopState = TrailingStopState.PENDING
    exit_fill_price: Decimal | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class TrailingStopManager:
    """Manages trailing stop orders.

    Places an initial stop order and ratchets it upward as the market price
    rises. Uses cancel_and_replace to efficiently update the resting stop.
    """

    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None) -> None:
        self._bus = event_bus
        self._exec = exec_adapter
        self._log = get_logger("orders.trailing_stop")
        self._stops: dict[str, TrailingStop] = {}
        self._order_to_stop: dict[str, str] = {}  # stop_order_id → trailing_stop_id
        self._monitored_symbols: set[str] = set()

    async def create_trailing_stop(
        self,
        symbol: str,
        quantity: Decimal,
        current_price: Decimal,
        trail_amount: Decimal | None = None,
        trail_percent: Decimal | None = None,
    ) -> TrailingStop:
        """Create and activate a trailing stop.

        Args:
            symbol: Ticker symbol.
            quantity: Number of shares to protect.
            current_price: Current market price (used to set initial stop).
            trail_amount: Absolute dollar trail (mutually exclusive with trail_percent).
            trail_percent: Percentage trail as decimal (e.g., 0.05 for 5%).

        Returns:
            The created TrailingStop instance.
        """
        if not self._exec:
            raise RuntimeError("No execution adapter configured")
        if trail_amount is None and trail_percent is None:
            raise ValueError("Must provide trail_amount or trail_percent")
        if trail_amount is not None and trail_percent is not None:
            raise ValueError("Provide trail_amount or trail_percent, not both")
        if trail_amount is not None and trail_amount <= 0:
            raise ValueError("trail_amount must be positive")
        if trail_percent is not None and (trail_percent <= 0 or trail_percent >= 1):
            raise ValueError("trail_percent must be between 0 and 1 (exclusive)")
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        ts_id = str(uuid.uuid4())

        # Calculate initial stop price
        if trail_amount is not None:
            stop_price = current_price - trail_amount
        else:
            stop_price = current_price * (1 - trail_percent)

        ts = TrailingStop(
            trailing_stop_id=ts_id,
            symbol=symbol,
            quantity=quantity,
            trail_amount=trail_amount,
            trail_percent=trail_percent,
            current_stop_price=stop_price,
            highest_price=current_price,
        )
        self._stops[ts_id] = ts

        # Place initial stop order
        await self._place_stop(ts)
        return ts

    def get_trailing_stop(self, ts_id: str) -> TrailingStop | None:
        return self._stops.get(ts_id)

    def get_active_trailing_stops(self) -> list[TrailingStop]:
        return [ts for ts in self._stops.values() if ts.state not in TRAILING_STOP_TERMINAL_STATES]

    async def cancel_trailing_stop(self, ts_id: str) -> bool:
        ts = self._stops.get(ts_id)
        if not ts or ts.state in TRAILING_STOP_TERMINAL_STATES:
            return False

        if ts.stop_order_id:
            try:
                await self._exec.cancel_order(ts.stop_order_id)
            except Exception as exc:
                self._log.warning("failed to cancel stop order", ts_id=ts_id, error=str(exc))

        await self._transition(ts, TrailingStopState.CANCELED)
        return True

    # ── Event Wiring ───────────────────────────────────────────────────

    async def wire_events(self) -> None:
        await self._bus.subscribe("quote", self._on_quote)
        await self._bus.subscribe("execution.order.filled", self._on_order_filled)
        await self._bus.subscribe("execution.order.cancelled", self._on_order_cancelled)

    async def unwire_events(self) -> None:
        await self._bus.unsubscribe("quote", self._on_quote)
        await self._bus.unsubscribe("execution.order.filled", self._on_order_filled)
        await self._bus.unsubscribe("execution.order.cancelled", self._on_order_cancelled)

    # ── Event Handlers ─────────────────────────────────────────────────

    async def _on_quote(self, channel: str, event: Any) -> None:
        if isinstance(event, QuoteTick):
            symbol = event.symbol
            bid_price = Decimal(str(event.bid_price))
        elif isinstance(event, dict) and "symbol" in event:
            symbol = event["symbol"]
            bid_price = Decimal(str(event.get("bid_price", 0)))
        else:
            return

        if symbol not in self._monitored_symbols:
            return

        for ts in self._stops.values():
            if ts.symbol == symbol and ts.state == TrailingStopState.ACTIVE:
                await self._maybe_update_stop(ts, bid_price)

    async def _on_order_filled(self, channel: str, event: Any) -> None:
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id or order_id not in self._order_to_stop:
            return

        ts_id = self._order_to_stop[order_id]
        ts = self._stops.get(ts_id)
        if not ts or ts.state != TrailingStopState.ACTIVE:
            return

        fill_price = event.get("fill_price") or event.get("avg_price")
        if fill_price is not None:
            ts.exit_fill_price = Decimal(str(fill_price))

        self._monitored_symbols.discard(ts.symbol)
        await self._transition(ts, TrailingStopState.COMPLETED)
        await self._bus.publish(TrailingStopChannel.TRAILING_STOP_COMPLETED, {
            "trailing_stop_id": ts_id,
            "symbol": ts.symbol,
            "exit_price": str(ts.exit_fill_price),
            "stop_price": str(ts.current_stop_price),
        })

    async def _on_order_cancelled(self, channel: str, event: Any) -> None:
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id or order_id not in self._order_to_stop:
            return

        ts_id = self._order_to_stop[order_id]
        ts = self._stops.get(ts_id)
        if not ts:
            return

        # If state is ACTIVE and we didn't initiate a cancel_and_replace,
        # this is an unexpected cancel. But during cancel_and_replace,
        # the old order gets cancelled — we handle that via the new order tracking.
        # Only treat as canceled if we're not in the middle of an update.
        if ts.state == TrailingStopState.ACTIVE and ts.stop_order_id == order_id:
            # Stop was cancelled externally
            self._monitored_symbols.discard(ts.symbol)
            await self._transition(ts, TrailingStopState.CANCELED)
            await self._bus.publish(TrailingStopChannel.TRAILING_STOP_CANCELED, {
                "trailing_stop_id": ts_id,
                "symbol": ts.symbol,
                "reason": "stop_order_cancelled",
            })

    # ── Internal ───────────────────────────────────────────────────────

    async def _place_stop(self, ts: TrailingStop) -> None:
        stop_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=ts.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=ts.quantity,
            stop_price=float(ts.current_stop_price),
        )
        ts.stop_order_id = stop_order.order_id
        self._order_to_stop[stop_order.order_id] = ts.trailing_stop_id

        try:
            await self._exec.submit_order(stop_order)
            self._monitored_symbols.add(ts.symbol)
            await self._transition(ts, TrailingStopState.ACTIVE)
            await self._bus.publish(TrailingStopChannel.TRAILING_STOP_PLACED, {
                "trailing_stop_id": ts.trailing_stop_id,
                "symbol": ts.symbol,
                "stop_price": str(ts.current_stop_price),
                "stop_order_id": stop_order.order_id,
            })
        except Exception as exc:
            self._log.error("stop placement failed", ts_id=ts.trailing_stop_id, error=str(exc))
            await self._transition(ts, TrailingStopState.ERROR)
            await self._bus.publish(TrailingStopChannel.TRAILING_STOP_ERROR, {
                "trailing_stop_id": ts.trailing_stop_id,
                "error": f"stop placement failed: {exc}",
            })

    async def _maybe_update_stop(self, ts: TrailingStop, bid_price: Decimal) -> None:
        """Recalculate stop level based on new bid; update if it moved up."""
        if bid_price <= ts.highest_price:
            return  # Price hasn't made a new high, nothing to do

        ts.highest_price = bid_price

        # Calculate new stop level
        if ts.trail_amount is not None:
            new_stop = bid_price - ts.trail_amount
        else:
            new_stop = bid_price * (1 - ts.trail_percent)

        # Ratchet: only move stop UP
        if new_stop <= ts.current_stop_price:
            return

        old_stop = ts.current_stop_price
        ts.current_stop_price = new_stop

        # Cancel and replace the resting stop order
        await self._replace_stop(ts, old_stop)

    async def _replace_stop(self, ts: TrailingStop, old_stop_price: Decimal) -> None:
        """Replace the resting stop order with a new stop price via cancel_and_replace."""
        old_order_id = ts.stop_order_id
        new_order_id = str(uuid.uuid4())

        # Use cancel_and_replace if available on the adapter
        if hasattr(self._exec, "cancel_and_replace"):
            try:
                result = await self._exec.cancel_and_replace(
                    order_id=old_order_id,
                    stop_price=ts.current_stop_price,
                )
                # Update tracking with the new order ID
                new_id = getattr(result, "order_id", new_order_id)
                self._order_to_stop.pop(old_order_id, None)
                ts.stop_order_id = new_id
                self._order_to_stop[new_id] = ts.trailing_stop_id

                await self._bus.publish(TrailingStopChannel.TRAILING_STOP_UPDATED, {
                    "trailing_stop_id": ts.trailing_stop_id,
                    "symbol": ts.symbol,
                    "old_stop_price": str(old_stop_price),
                    "new_stop_price": str(ts.current_stop_price),
                    "new_order_id": new_id,
                })
                return
            except Exception:
                # Fall through to manual cancel + replace
                pass

        # Fallback: manual cancel then re-place
        try:
            await self._exec.cancel_order(old_order_id)
        except Exception as exc:
            self._log.warning("cancel failed during trailing update", error=str(exc))
            # Revert stop price since we couldn't update
            ts.current_stop_price = old_stop_price
            return

        self._order_to_stop.pop(old_order_id, None)

        stop_order = Order(
            order_id=new_order_id,
            symbol=ts.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=ts.quantity,
            stop_price=float(ts.current_stop_price),
        )
        ts.stop_order_id = new_order_id
        self._order_to_stop[new_order_id] = ts.trailing_stop_id

        try:
            await self._exec.submit_order(stop_order)
            await self._bus.publish(TrailingStopChannel.TRAILING_STOP_UPDATED, {
                "trailing_stop_id": ts.trailing_stop_id,
                "symbol": ts.symbol,
                "old_stop_price": str(old_stop_price),
                "new_stop_price": str(ts.current_stop_price),
                "new_order_id": new_order_id,
            })
        except Exception as exc:
            self._log.error("stop re-placement failed", ts_id=ts.trailing_stop_id, error=str(exc))
            await self._transition(ts, TrailingStopState.ERROR)

    async def _transition(self, ts: TrailingStop, new_state: TrailingStopState) -> None:
        old_state = ts.state
        ts.state = new_state
        if new_state in TRAILING_STOP_TERMINAL_STATES:
            ts.completed_at = datetime.now(timezone.utc)
        self._log.info(
            "trailing stop state change",
            ts_id=ts.trailing_stop_id,
            from_state=str(old_state),
            to_state=str(new_state),
        )
        await self._bus.publish(TrailingStopChannel.TRAILING_STOP_STATE_CHANGE, {
            "trailing_stop_id": ts.trailing_stop_id,
            "symbol": ts.symbol,
            "from_state": str(old_state),
            "to_state": str(new_state),
        })
