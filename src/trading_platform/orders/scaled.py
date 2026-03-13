"""Scaled order manager for multi-tranche entries and exits.

Supports scaled exits (multiple take-profit levels) and scaled entries
(multiple limit buy levels), each with proportional quantity allocation.
Stop-loss quantity adjusts as tranches fill.
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


class ScaledOrderState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"


SCALED_ORDER_TERMINAL_STATES = frozenset({
    ScaledOrderState.COMPLETED,
    ScaledOrderState.CANCELED,
    ScaledOrderState.ERROR,
})


class ScaledOrderChannel(StrEnum):
    SCALED_EXIT_PLACED = "scaled.exit.placed"
    SCALED_EXIT_TRANCHE_FILLED = "scaled.exit.tranche_filled"
    SCALED_EXIT_COMPLETED = "scaled.exit.completed"
    SCALED_EXIT_STOPPED_OUT = "scaled.exit.stopped_out"
    SCALED_ENTRY_PLACED = "scaled.entry.placed"
    SCALED_ENTRY_TRANCHE_FILLED = "scaled.entry.tranche_filled"
    SCALED_ENTRY_COMPLETED = "scaled.entry.completed"
    SCALED_STOP_ADJUSTED = "scaled.stop.adjusted"
    SCALED_STATE_CHANGE = "scaled.state_change"
    SCALED_ERROR = "scaled.error"
    SCALED_CANCELED = "scaled.canceled"


@dataclass
class Tranche:
    """A single price/quantity level in a scaled order."""
    price: Decimal
    quantity: Decimal
    filled: bool = False
    order_id: str | None = None  # For scaled entries (limit orders)


@dataclass
class ScaledExitOrder:
    """Tracks a scaled exit (multiple take-profit levels with a shared stop-loss)."""
    scaled_id: str
    symbol: str
    total_quantity: Decimal
    tranches: list[Tranche]
    stop_loss_price: Decimal
    stop_order_id: str | None = None
    remaining_quantity: Decimal = Decimal("0")
    state: ScaledOrderState = ScaledOrderState.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        self.remaining_quantity = self.total_quantity


@dataclass
class ScaledEntryOrder:
    """Tracks a scaled entry (multiple limit buy levels with progressive stop-loss)."""
    scaled_id: str
    symbol: str
    total_quantity: Decimal
    tranches: list[Tranche]
    stop_loss_price: Decimal
    stop_order_id: str | None = None
    filled_quantity: Decimal = Decimal("0")
    state: ScaledOrderState = ScaledOrderState.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class ScaledOrderManager:
    """Manages scaled entries and exits with adjusting stop-loss protection."""

    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None) -> None:
        self._bus = event_bus
        self._exec = exec_adapter
        self._log = get_logger("orders.scaled")

        self._exits: dict[str, ScaledExitOrder] = {}
        self._entries: dict[str, ScaledEntryOrder] = {}

        # Reverse lookups
        self._stop_to_exit: dict[str, str] = {}  # stop_order_id → scaled_id
        self._stop_to_entry: dict[str, str] = {}  # stop_order_id → scaled_id
        self._entry_order_to_entry: dict[str, tuple[str, int]] = {}  # order_id → (scaled_id, tranche_idx)

        # Symbols being monitored for exit tranches
        self._exit_monitored_symbols: set[str] = set()

    # ── Scaled Exits ──────────────────────────────────────────────────

    async def create_scaled_exit(
        self,
        symbol: str,
        total_quantity: Decimal,
        take_profit_levels: list[tuple[Decimal, Decimal]],
        stop_loss_price: Decimal,
    ) -> ScaledExitOrder:
        """Create a scaled exit with multiple take-profit tranches.

        Args:
            symbol: Ticker symbol.
            total_quantity: Total position size.
            take_profit_levels: List of (price, quantity_percent) tuples.
                Percentages must sum to 1.0.
            stop_loss_price: Stop-loss price for remaining position.

        Returns:
            The created ScaledExitOrder.
        """
        if not self._exec:
            raise RuntimeError("No execution adapter configured")
        if total_quantity <= 0:
            raise ValueError("total_quantity must be positive")
        if not take_profit_levels:
            raise ValueError("Must provide at least one take_profit_level")

        # Validate percentages sum to ~1.0
        pct_sum = sum(pct for _, pct in take_profit_levels)
        if abs(pct_sum - Decimal("1")) > Decimal("0.001"):
            raise ValueError(f"take_profit_level percentages must sum to 1.0, got {pct_sum}")

        # Build tranches
        tranches = []
        for price, pct in take_profit_levels:
            qty = (total_quantity * pct).quantize(Decimal("1"))
            tranches.append(Tranche(price=price, quantity=qty))

        # Fix rounding: adjust last tranche so quantities sum to total
        assigned = sum(t.quantity for t in tranches)
        if assigned != total_quantity:
            tranches[-1].quantity += total_quantity - assigned

        scaled_id = str(uuid.uuid4())
        order = ScaledExitOrder(
            scaled_id=scaled_id,
            symbol=symbol,
            total_quantity=total_quantity,
            tranches=tranches,
            stop_loss_price=stop_loss_price,
        )
        self._exits[scaled_id] = order

        # Place stop-loss for full position
        await self._place_exit_stop(order)
        return order

    # ── Scaled Entries ─────────────────────────────────────────────────

    async def create_scaled_entry(
        self,
        symbol: str,
        total_quantity: Decimal,
        entry_levels: list[tuple[Decimal, Decimal]],
        stop_loss_price: Decimal,
    ) -> ScaledEntryOrder:
        """Create a scaled entry with multiple limit buy levels.

        Args:
            symbol: Ticker symbol.
            total_quantity: Total desired position size.
            entry_levels: List of (price, quantity_percent) tuples.
            stop_loss_price: Stop-loss price for filled quantity.

        Returns:
            The created ScaledEntryOrder.
        """
        if not self._exec:
            raise RuntimeError("No execution adapter configured")
        if total_quantity <= 0:
            raise ValueError("total_quantity must be positive")
        if not entry_levels:
            raise ValueError("Must provide at least one entry_level")

        pct_sum = sum(pct for _, pct in entry_levels)
        if abs(pct_sum - Decimal("1")) > Decimal("0.001"):
            raise ValueError(f"entry_level percentages must sum to 1.0, got {pct_sum}")

        tranches = []
        for price, pct in entry_levels:
            qty = (total_quantity * pct).quantize(Decimal("1"))
            tranches.append(Tranche(price=price, quantity=qty))

        assigned = sum(t.quantity for t in tranches)
        if assigned != total_quantity:
            tranches[-1].quantity += total_quantity - assigned

        scaled_id = str(uuid.uuid4())
        entry = ScaledEntryOrder(
            scaled_id=scaled_id,
            symbol=symbol,
            total_quantity=total_quantity,
            tranches=tranches,
            stop_loss_price=stop_loss_price,
        )
        self._entries[scaled_id] = entry

        # Place limit buy orders at each level
        await self._place_entry_orders(entry)
        return entry

    # ── Query ──────────────────────────────────────────────────────────

    def get_scaled_exit(self, scaled_id: str) -> ScaledExitOrder | None:
        return self._exits.get(scaled_id)

    def get_scaled_entry(self, scaled_id: str) -> ScaledEntryOrder | None:
        return self._entries.get(scaled_id)

    # ── Event Wiring ──────────────────────────────────────────────────

    async def wire_events(self) -> None:
        await self._bus.subscribe("quote", self._on_quote)
        await self._bus.subscribe("execution.order.filled", self._on_order_filled)
        await self._bus.subscribe("execution.order.cancelled", self._on_order_cancelled)

    async def unwire_events(self) -> None:
        await self._bus.unsubscribe("quote", self._on_quote)
        await self._bus.unsubscribe("execution.order.filled", self._on_order_filled)
        await self._bus.unsubscribe("execution.order.cancelled", self._on_order_cancelled)

    # ── Event Handlers ────────────────────────────────────────────────

    async def _on_quote(self, channel: str, event: Any) -> None:
        """Monitor bid prices for scaled exit tranche triggers."""
        if isinstance(event, QuoteTick):
            symbol = event.symbol
            bid_price = Decimal(str(event.bid_price))
        elif isinstance(event, dict) and "symbol" in event:
            symbol = event["symbol"]
            bid_price = Decimal(str(event.get("bid_price", 0)))
        else:
            return

        if symbol not in self._exit_monitored_symbols:
            return

        for order in self._exits.values():
            if order.symbol == symbol and order.state == ScaledOrderState.ACTIVE:
                await self._check_exit_tranches(order, bid_price)

    async def _on_order_filled(self, channel: str, event: Any) -> None:
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id:
            return

        # Exit stop-loss filled
        if order_id in self._stop_to_exit:
            scaled_id = self._stop_to_exit[order_id]
            order = self._exits.get(scaled_id)
            if order and order.state == ScaledOrderState.ACTIVE:
                self._exit_monitored_symbols.discard(order.symbol)
                await self._transition_exit(order, ScaledOrderState.COMPLETED)
                await self._bus.publish(ScaledOrderChannel.SCALED_EXIT_STOPPED_OUT, {
                    "scaled_id": scaled_id,
                    "symbol": order.symbol,
                    "remaining_quantity": str(order.remaining_quantity),
                })
            return

        # Entry stop-loss filled
        if order_id in self._stop_to_entry:
            scaled_id = self._stop_to_entry[order_id]
            entry = self._entries.get(scaled_id)
            if entry and entry.state == ScaledOrderState.ACTIVE:
                await self._transition_entry(entry, ScaledOrderState.COMPLETED)
                await self._bus.publish(ScaledOrderChannel.SCALED_ENTRY_COMPLETED, {
                    "scaled_id": scaled_id,
                    "symbol": entry.symbol,
                    "reason": "stopped_out",
                    "filled_quantity": str(entry.filled_quantity),
                })
            return

        # Entry tranche filled
        if order_id in self._entry_order_to_entry:
            scaled_id, tranche_idx = self._entry_order_to_entry[order_id]
            entry = self._entries.get(scaled_id)
            if entry and entry.state == ScaledOrderState.ACTIVE:
                tranche = entry.tranches[tranche_idx]
                tranche.filled = True
                entry.filled_quantity += tranche.quantity

                await self._bus.publish(ScaledOrderChannel.SCALED_ENTRY_TRANCHE_FILLED, {
                    "scaled_id": scaled_id,
                    "symbol": entry.symbol,
                    "tranche_price": str(tranche.price),
                    "tranche_quantity": str(tranche.quantity),
                    "total_filled": str(entry.filled_quantity),
                })

                # Place or adjust stop-loss for filled quantity
                await self._adjust_entry_stop(entry)

                # Check if all tranches filled
                if all(t.filled for t in entry.tranches):
                    await self._transition_entry(entry, ScaledOrderState.COMPLETED)
                    await self._bus.publish(ScaledOrderChannel.SCALED_ENTRY_COMPLETED, {
                        "scaled_id": scaled_id,
                        "symbol": entry.symbol,
                        "reason": "all_tranches_filled",
                        "filled_quantity": str(entry.filled_quantity),
                    })

    async def _on_order_cancelled(self, channel: str, event: Any) -> None:
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id:
            return

        # Exit stop cancelled (could be during tranche fill adjustment)
        if order_id in self._stop_to_exit:
            scaled_id = self._stop_to_exit[order_id]
            order = self._exits.get(scaled_id)
            if order and order.state == ScaledOrderState.ACTIVE and order.stop_order_id == order_id:
                # Only treat as canceled if this is still the active stop
                # (during cancel_and_replace, old stop gets cancelled)
                pass  # Handled by replace flow

    # ── Internal: Scaled Exits ─────────────────────────────────────────

    async def _place_exit_stop(self, order: ScaledExitOrder) -> None:
        """Place the initial stop-loss for the full exit position."""
        stop_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=order.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=order.total_quantity,
            stop_price=float(order.stop_loss_price),
        )
        order.stop_order_id = stop_order.order_id
        self._stop_to_exit[stop_order.order_id] = order.scaled_id

        try:
            await self._exec.submit_order(stop_order)
            self._exit_monitored_symbols.add(order.symbol)
            await self._transition_exit(order, ScaledOrderState.ACTIVE)
            await self._bus.publish(ScaledOrderChannel.SCALED_EXIT_PLACED, {
                "scaled_id": order.scaled_id,
                "symbol": order.symbol,
                "tranches": len(order.tranches),
                "stop_price": str(order.stop_loss_price),
                "stop_order_id": stop_order.order_id,
            })
        except Exception as exc:
            self._log.error("exit stop placement failed", scaled_id=order.scaled_id, error=str(exc))
            await self._transition_exit(order, ScaledOrderState.ERROR)
            await self._bus.publish(ScaledOrderChannel.SCALED_ERROR, {
                "scaled_id": order.scaled_id,
                "error": f"stop placement failed: {exc}",
            })

    async def _check_exit_tranches(self, order: ScaledExitOrder, bid_price: Decimal) -> None:
        """Check if any unfilled exit tranche has been triggered by bid price."""
        for tranche in order.tranches:
            if tranche.filled:
                continue
            if bid_price >= tranche.price:
                await self._execute_exit_tranche(order, tranche)

    async def _execute_exit_tranche(self, order: ScaledExitOrder, tranche: Tranche) -> None:
        """Execute a market sell for a triggered exit tranche."""
        tranche.filled = True
        order.remaining_quantity -= tranche.quantity

        # Place market sell for the tranche
        sell_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=order.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=tranche.quantity,
        )

        try:
            await self._exec.submit_order(sell_order)
            await self._bus.publish(ScaledOrderChannel.SCALED_EXIT_TRANCHE_FILLED, {
                "scaled_id": order.scaled_id,
                "symbol": order.symbol,
                "tranche_price": str(tranche.price),
                "tranche_quantity": str(tranche.quantity),
                "remaining_quantity": str(order.remaining_quantity),
            })
        except Exception as exc:
            self._log.error("tranche sell failed", scaled_id=order.scaled_id, error=str(exc))
            tranche.filled = False
            order.remaining_quantity += tranche.quantity
            return

        # Adjust stop-loss quantity for remaining position
        if order.remaining_quantity > 0:
            await self._adjust_exit_stop(order)
        else:
            # All tranches filled — cancel the stop-loss
            if order.stop_order_id:
                try:
                    await self._exec.cancel_order(order.stop_order_id)
                except Exception as exc:
                    self._log.warning("stop cancel failed after all tranches", error=str(exc))
            self._exit_monitored_symbols.discard(order.symbol)
            await self._transition_exit(order, ScaledOrderState.COMPLETED)
            await self._bus.publish(ScaledOrderChannel.SCALED_EXIT_COMPLETED, {
                "scaled_id": order.scaled_id,
                "symbol": order.symbol,
            })

    async def _adjust_exit_stop(self, order: ScaledExitOrder) -> None:
        """Adjust stop-loss quantity to match remaining position."""
        old_order_id = order.stop_order_id

        # Use cancel_and_replace if available
        if hasattr(self._exec, "cancel_and_replace"):
            try:
                result = await self._exec.cancel_and_replace(
                    order_id=old_order_id,
                    quantity=order.remaining_quantity,
                )
                new_id = getattr(result, "order_id", str(uuid.uuid4()))
                self._stop_to_exit.pop(old_order_id, None)
                order.stop_order_id = new_id
                self._stop_to_exit[new_id] = order.scaled_id

                await self._bus.publish(ScaledOrderChannel.SCALED_STOP_ADJUSTED, {
                    "scaled_id": order.scaled_id,
                    "symbol": order.symbol,
                    "new_quantity": str(order.remaining_quantity),
                    "new_order_id": new_id,
                })
                return
            except Exception:
                pass  # Fall through to manual approach

        # Fallback: cancel and re-place
        try:
            await self._exec.cancel_order(old_order_id)
        except Exception as exc:
            self._log.warning("stop cancel failed during adjustment", error=str(exc))
            return

        self._stop_to_exit.pop(old_order_id, None)

        new_stop = Order(
            order_id=str(uuid.uuid4()),
            symbol=order.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=order.remaining_quantity,
            stop_price=float(order.stop_loss_price),
        )
        order.stop_order_id = new_stop.order_id
        self._stop_to_exit[new_stop.order_id] = order.scaled_id

        try:
            await self._exec.submit_order(new_stop)
            await self._bus.publish(ScaledOrderChannel.SCALED_STOP_ADJUSTED, {
                "scaled_id": order.scaled_id,
                "symbol": order.symbol,
                "new_quantity": str(order.remaining_quantity),
                "new_order_id": new_stop.order_id,
            })
        except Exception as exc:
            self._log.error("stop re-placement failed", scaled_id=order.scaled_id, error=str(exc))

    # ── Internal: Scaled Entries ────────────────────────────────────────

    async def _place_entry_orders(self, entry: ScaledEntryOrder) -> None:
        """Place limit buy orders at each entry tranche level."""
        placed_any = False
        for idx, tranche in enumerate(entry.tranches):
            order = Order(
                order_id=str(uuid.uuid4()),
                symbol=entry.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=tranche.quantity,
                limit_price=float(tranche.price),
            )
            tranche.order_id = order.order_id
            self._entry_order_to_entry[order.order_id] = (entry.scaled_id, idx)

            try:
                await self._exec.submit_order(order)
                placed_any = True
            except Exception as exc:
                self._log.error(
                    "entry tranche placement failed",
                    scaled_id=entry.scaled_id,
                    tranche_idx=idx,
                    error=str(exc),
                )

        if placed_any:
            await self._transition_entry(entry, ScaledOrderState.ACTIVE)
            await self._bus.publish(ScaledOrderChannel.SCALED_ENTRY_PLACED, {
                "scaled_id": entry.scaled_id,
                "symbol": entry.symbol,
                "tranches": len(entry.tranches),
            })
        else:
            await self._transition_entry(entry, ScaledOrderState.ERROR)
            await self._bus.publish(ScaledOrderChannel.SCALED_ERROR, {
                "scaled_id": entry.scaled_id,
                "error": "no entry tranches could be placed",
            })

    async def _adjust_entry_stop(self, entry: ScaledEntryOrder) -> None:
        """Place or adjust stop-loss to cover all filled entry quantity."""
        if entry.stop_order_id is not None:
            # Adjust existing stop
            old_order_id = entry.stop_order_id

            if hasattr(self._exec, "cancel_and_replace"):
                try:
                    result = await self._exec.cancel_and_replace(
                        order_id=old_order_id,
                        quantity=entry.filled_quantity,
                    )
                    new_id = getattr(result, "order_id", str(uuid.uuid4()))
                    self._stop_to_entry.pop(old_order_id, None)
                    entry.stop_order_id = new_id
                    self._stop_to_entry[new_id] = entry.scaled_id

                    await self._bus.publish(ScaledOrderChannel.SCALED_STOP_ADJUSTED, {
                        "scaled_id": entry.scaled_id,
                        "symbol": entry.symbol,
                        "new_quantity": str(entry.filled_quantity),
                        "new_order_id": new_id,
                    })
                    return
                except Exception:
                    pass

            # Fallback: cancel and re-place
            try:
                await self._exec.cancel_order(old_order_id)
            except Exception as exc:
                self._log.warning("stop cancel failed during entry adjustment", error=str(exc))
                return

            self._stop_to_entry.pop(old_order_id, None)

        # Place new stop for filled quantity
        stop = Order(
            order_id=str(uuid.uuid4()),
            symbol=entry.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=entry.filled_quantity,
            stop_price=float(entry.stop_loss_price),
        )
        entry.stop_order_id = stop.order_id
        self._stop_to_entry[stop.order_id] = entry.scaled_id

        try:
            await self._exec.submit_order(stop)
            await self._bus.publish(ScaledOrderChannel.SCALED_STOP_ADJUSTED, {
                "scaled_id": entry.scaled_id,
                "symbol": entry.symbol,
                "new_quantity": str(entry.filled_quantity),
                "new_order_id": stop.order_id,
            })
        except Exception as exc:
            self._log.error("entry stop placement failed", scaled_id=entry.scaled_id, error=str(exc))

    # ── State Machine ──────────────────────────────────────────────────

    async def _transition_exit(self, order: ScaledExitOrder, new_state: ScaledOrderState) -> None:
        old_state = order.state
        order.state = new_state
        if new_state in SCALED_ORDER_TERMINAL_STATES:
            order.completed_at = datetime.now(timezone.utc)
        self._log.info("scaled exit state change", scaled_id=order.scaled_id, from_state=str(old_state), to_state=str(new_state))
        await self._bus.publish(ScaledOrderChannel.SCALED_STATE_CHANGE, {
            "scaled_id": order.scaled_id,
            "symbol": order.symbol,
            "from_state": str(old_state),
            "to_state": str(new_state),
        })

    async def _transition_entry(self, entry: ScaledEntryOrder, new_state: ScaledOrderState) -> None:
        old_state = entry.state
        entry.state = new_state
        if new_state in SCALED_ORDER_TERMINAL_STATES:
            entry.completed_at = datetime.now(timezone.utc)
        self._log.info("scaled entry state change", scaled_id=entry.scaled_id, from_state=str(old_state), to_state=str(new_state))
        await self._bus.publish(ScaledOrderChannel.SCALED_STATE_CHANGE, {
            "scaled_id": entry.scaled_id,
            "symbol": entry.symbol,
            "from_state": str(old_state),
            "to_state": str(new_state),
        })
