"""Scaled order manager for multi-tranche entries and exits.

Supports:
- Scaled exits: multiple take-profit levels with percentage-based quantity allocation
- Scaled entries: multiple entry levels with limit orders
- Automatic stop-loss quantity adjustment as tranches fill
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from trading_platform.adapters.base import ExecAdapter
from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Order, QuoteTick


class ScaledOrderState(StrEnum):
    """State machine for scaled orders."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"


SCALED_TERMINAL_STATES = frozenset({
    ScaledOrderState.COMPLETED,
    ScaledOrderState.CANCELED,
    ScaledOrderState.ERROR,
})


class ScaledOrderChannel(StrEnum):
    """Event bus channels for scaled order events."""
    SCALED_EXIT_CREATED = "scaled_exit.created"
    SCALED_EXIT_TRANCHE_FILLED = "scaled_exit.tranche_filled"
    SCALED_EXIT_COMPLETED = "scaled_exit.completed"
    SCALED_ENTRY_CREATED = "scaled_entry.created"
    SCALED_ENTRY_TRANCHE_FILLED = "scaled_entry.tranche_filled"
    SCALED_ENTRY_COMPLETED = "scaled_entry.completed"
    SCALED_ORDER_CANCELED = "scaled_order.canceled"
    SCALED_ORDER_ERROR = "scaled_order.error"
    SCALED_ORDER_STATE_CHANGE = "scaled_order.state_change"


class Tranche(BaseModel):
    """A single tranche in a scaled order."""
    price: Decimal
    quantity: Decimal
    quantity_percent: Decimal
    filled: bool = False
    order_id: str | None = None
    fill_price: Decimal | None = None


class ScaledExitOrder(BaseModel):
    """Scaled exit order with multiple take-profit tranches."""
    scaled_order_id: str
    symbol: str
    total_quantity: Decimal
    remaining_quantity: Decimal
    tranches: list[Tranche]
    stop_loss_order_id: str | None = None
    stop_loss_price: Decimal | None = None
    state: ScaledOrderState = ScaledOrderState.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    model_config = {"ser_json_timedelta": "float"}


class ScaledEntryOrder(BaseModel):
    """Scaled entry order with multiple entry tranches."""
    scaled_order_id: str
    symbol: str
    total_quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    tranches: list[Tranche]
    stop_loss_price: Decimal | None = None
    stop_loss_order_id: str | None = None
    state: ScaledOrderState = ScaledOrderState.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    model_config = {"ser_json_timedelta": "float"}


class ScaledOrderManager:
    """Manages scaled entries and exits with automatic stop-loss adjustment.

    Scaled exits monitor bid prices and execute market sells at each tranche
    level. The resting stop-loss quantity is adjusted as tranches fill.

    Scaled entries place limit buy orders at each level. Stop-loss is placed
    after the first fill and adjusted as more tranches fill.
    """

    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None) -> None:
        self._bus = event_bus
        self._exec = exec_adapter
        self._log = get_logger("orders.scaled")
        self._exits: dict[str, ScaledExitOrder] = {}
        self._entries: dict[str, ScaledEntryOrder] = {}
        # Reverse lookups
        self._exit_sell_to_scaled: dict[str, tuple[str, int]] = {}  # order_id → (scaled_id, tranche_idx)
        self._entry_buy_to_scaled: dict[str, tuple[str, int]] = {}  # order_id → (scaled_id, tranche_idx)
        self._entry_stop_to_scaled: dict[str, str] = {}  # stop order_id → scaled entry id
        self._monitored_exit_symbols: set[str] = set()

    # ── Scaled Exits ───────────────────────────────────────────────────

    async def create_scaled_exit(
        self,
        symbol: str,
        total_quantity: Decimal,
        levels: list[tuple[Decimal, Decimal]],
        stop_loss_order_id: str | None = None,
        stop_loss_price: Decimal | None = None,
    ) -> ScaledExitOrder:
        """Create a scaled exit order with multiple take-profit tranches.

        Args:
            symbol: Ticker symbol.
            total_quantity: Total position size to exit.
            levels: List of (price, quantity_percent) tuples.
            stop_loss_order_id: Existing resting stop order to adjust.
            stop_loss_price: Stop-loss price for quantity adjustments.

        Returns:
            The created ScaledExitOrder.
        """
        if not self._exec:
            raise RuntimeError("No execution adapter configured")
        if not levels:
            raise ValueError("At least one exit level is required")
        if total_quantity <= 0:
            raise ValueError("total_quantity must be positive")

        total_pct = sum(pct for _, pct in levels)
        if abs(total_pct - Decimal("1")) > Decimal("0.001"):
            raise ValueError("Level percentages must sum to 1.0")

        tranches = []
        for price, pct in levels:
            qty = (total_quantity * pct).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if qty <= 0:
                qty = Decimal("1")
            tranches.append(Tranche(price=price, quantity=qty, quantity_percent=pct))

        # Adjust last tranche to account for rounding
        allocated = sum(t.quantity for t in tranches[:-1])
        tranches[-1].quantity = total_quantity - allocated

        scaled_id = str(uuid.uuid4())
        scaled = ScaledExitOrder(
            scaled_order_id=scaled_id,
            symbol=symbol,
            total_quantity=total_quantity,
            remaining_quantity=total_quantity,
            tranches=tranches,
            stop_loss_order_id=stop_loss_order_id,
            stop_loss_price=stop_loss_price,
        )
        self._exits[scaled_id] = scaled
        scaled.state = ScaledOrderState.ACTIVE
        self._monitored_exit_symbols.add(symbol)

        await self._bus.publish(ScaledOrderChannel.SCALED_EXIT_CREATED, {
            "scaled_order_id": scaled_id,
            "symbol": symbol,
            "tranches": len(tranches),
        })
        return scaled

    # ── Scaled Entries ─────────────────────────────────────────────────

    async def create_scaled_entry(
        self,
        symbol: str,
        total_quantity: Decimal,
        levels: list[tuple[Decimal, Decimal]],
        stop_loss_price: Decimal | None = None,
    ) -> ScaledEntryOrder:
        """Create a scaled entry order with multiple limit buy tranches.

        Args:
            symbol: Ticker symbol.
            total_quantity: Total shares to accumulate.
            levels: List of (price, quantity_percent) tuples.
            stop_loss_price: Price for stop-loss (placed/adjusted as entries fill).

        Returns:
            The created ScaledEntryOrder.
        """
        if not self._exec:
            raise RuntimeError("No execution adapter configured")
        if not levels:
            raise ValueError("At least one entry level is required")
        if total_quantity <= 0:
            raise ValueError("total_quantity must be positive")

        total_pct = sum(pct for _, pct in levels)
        if abs(total_pct - Decimal("1")) > Decimal("0.001"):
            raise ValueError("Level percentages must sum to 1.0")

        tranches = []
        for price, pct in levels:
            qty = (total_quantity * pct).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if qty <= 0:
                qty = Decimal("1")
            tranches.append(Tranche(price=price, quantity=qty, quantity_percent=pct))

        # Adjust last tranche for rounding
        allocated = sum(t.quantity for t in tranches[:-1])
        tranches[-1].quantity = total_quantity - allocated

        scaled_id = str(uuid.uuid4())
        scaled = ScaledEntryOrder(
            scaled_order_id=scaled_id,
            symbol=symbol,
            total_quantity=total_quantity,
            tranches=tranches,
            stop_loss_price=stop_loss_price,
        )
        self._entries[scaled_id] = scaled

        # Place limit buy orders for each tranche
        await self._place_entry_tranches(scaled)
        return scaled

    # ── Public API ─────────────────────────────────────────────────────

    def get_scaled_exit(self, scaled_order_id: str) -> ScaledExitOrder | None:
        return self._exits.get(scaled_order_id)

    def get_scaled_entry(self, scaled_order_id: str) -> ScaledEntryOrder | None:
        return self._entries.get(scaled_order_id)

    async def cancel_scaled_order(self, scaled_order_id: str) -> bool:
        """Cancel a scaled exit or entry order."""
        if scaled_order_id in self._exits:
            scaled = self._exits[scaled_order_id]
            if scaled.state in SCALED_TERMINAL_STATES:
                return False
            scaled.state = ScaledOrderState.CANCELED
            scaled.completed_at = datetime.now(timezone.utc)
            self._monitored_exit_symbols.discard(scaled.symbol)
            await self._bus.publish(ScaledOrderChannel.SCALED_ORDER_CANCELED, {
                "scaled_order_id": scaled_order_id,
            })
            return True

        if scaled_order_id in self._entries:
            scaled_entry = self._entries[scaled_order_id]
            if scaled_entry.state in SCALED_TERMINAL_STATES:
                return False
            # Cancel unfilled entry orders
            for tranche in scaled_entry.tranches:
                if not tranche.filled and tranche.order_id:
                    try:
                        await self._exec.cancel_order(tranche.order_id)
                    except Exception:
                        pass
            # Cancel stop if placed
            if scaled_entry.stop_loss_order_id:
                try:
                    await self._exec.cancel_order(scaled_entry.stop_loss_order_id)
                except Exception:
                    pass
            scaled_entry.state = ScaledOrderState.CANCELED
            scaled_entry.completed_at = datetime.now(timezone.utc)
            await self._bus.publish(ScaledOrderChannel.SCALED_ORDER_CANCELED, {
                "scaled_order_id": scaled_order_id,
            })
            return True

        return False

    # ── Event Wiring ───────────────────────────────────────────────────

    async def wire_events(self) -> None:
        await self._bus.subscribe("quote", self._on_quote)
        await self._bus.subscribe("execution.order.filled", self._on_order_filled)

    async def unwire_events(self) -> None:
        await self._bus.unsubscribe("quote", self._on_quote)
        await self._bus.unsubscribe("execution.order.filled", self._on_order_filled)

    # ── Event Handlers ─────────────────────────────────────────────────

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

        if symbol not in self._monitored_exit_symbols:
            return

        for scaled in self._exits.values():
            if scaled.symbol != symbol or scaled.state != ScaledOrderState.ACTIVE:
                continue

            for i, tranche in enumerate(scaled.tranches):
                if tranche.filled:
                    continue
                if bid_price >= tranche.price:
                    await self._execute_exit_tranche(scaled, i)

    async def _on_order_filled(self, channel: str, event: Any) -> None:
        """Handle fills for scaled exit sell orders and scaled entry buy orders."""
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id:
            return

        # Scaled exit sell fill
        if order_id in self._exit_sell_to_scaled:
            scaled_id, tranche_idx = self._exit_sell_to_scaled[order_id]
            scaled = self._exits.get(scaled_id)
            if scaled and scaled.state == ScaledOrderState.ACTIVE:
                tranche = scaled.tranches[tranche_idx]
                fill_price = event.get("fill_price") or event.get("avg_price")
                if fill_price is not None:
                    tranche.fill_price = Decimal(str(fill_price))
                tranche.filled = True
                scaled.remaining_quantity -= tranche.quantity

                await self._bus.publish(ScaledOrderChannel.SCALED_EXIT_TRANCHE_FILLED, {
                    "scaled_order_id": scaled_id,
                    "symbol": scaled.symbol,
                    "tranche_index": tranche_idx,
                    "tranche_price": str(tranche.price),
                    "tranche_quantity": str(tranche.quantity),
                    "remaining_quantity": str(scaled.remaining_quantity),
                })

                # Adjust stop-loss quantity for remaining position
                if scaled.remaining_quantity > 0:
                    await self._adjust_exit_stop_quantity(scaled)
                else:
                    # All tranches filled — cancel stop, mark complete
                    if scaled.stop_loss_order_id:
                        try:
                            await self._exec.cancel_order(scaled.stop_loss_order_id)
                        except Exception as exc:
                            self._log.warning("failed to cancel stop after all tranches", error=str(exc))
                    scaled.state = ScaledOrderState.COMPLETED
                    scaled.completed_at = datetime.now(timezone.utc)
                    self._monitored_exit_symbols.discard(scaled.symbol)
                    await self._bus.publish(ScaledOrderChannel.SCALED_EXIT_COMPLETED, {
                        "scaled_order_id": scaled_id,
                        "symbol": scaled.symbol,
                    })
            return

        # Scaled entry buy fill
        if order_id in self._entry_buy_to_scaled:
            scaled_id, tranche_idx = self._entry_buy_to_scaled[order_id]
            scaled_entry = self._entries.get(scaled_id)
            if scaled_entry and scaled_entry.state == ScaledOrderState.ACTIVE:
                tranche = scaled_entry.tranches[tranche_idx]
                fill_price = event.get("fill_price") or event.get("avg_price")
                if fill_price is not None:
                    tranche.fill_price = Decimal(str(fill_price))
                tranche.filled = True
                scaled_entry.filled_quantity += tranche.quantity

                await self._bus.publish(ScaledOrderChannel.SCALED_ENTRY_TRANCHE_FILLED, {
                    "scaled_order_id": scaled_id,
                    "symbol": scaled_entry.symbol,
                    "tranche_index": tranche_idx,
                    "tranche_quantity": str(tranche.quantity),
                    "total_filled": str(scaled_entry.filled_quantity),
                })

                # Place or adjust stop-loss for filled quantity
                await self._adjust_entry_stop(scaled_entry)

                # Check if all tranches filled
                if all(t.filled for t in scaled_entry.tranches):
                    scaled_entry.state = ScaledOrderState.COMPLETED
                    scaled_entry.completed_at = datetime.now(timezone.utc)
                    await self._bus.publish(ScaledOrderChannel.SCALED_ENTRY_COMPLETED, {
                        "scaled_order_id": scaled_id,
                        "symbol": scaled_entry.symbol,
                        "total_filled": str(scaled_entry.filled_quantity),
                    })
            return

        # Scaled entry stop-loss fill
        if order_id in self._entry_stop_to_scaled:
            scaled_id = self._entry_stop_to_scaled[order_id]
            scaled_entry = self._entries.get(scaled_id)
            if scaled_entry and scaled_entry.state == ScaledOrderState.ACTIVE:
                # Stop triggered — cancel unfilled entry tranches
                for tranche in scaled_entry.tranches:
                    if not tranche.filled and tranche.order_id:
                        try:
                            await self._exec.cancel_order(tranche.order_id)
                        except Exception:
                            pass
                scaled_entry.state = ScaledOrderState.COMPLETED
                scaled_entry.completed_at = datetime.now(timezone.utc)

    # ── Internal: Scaled Exits ─────────────────────────────────────────

    async def _execute_exit_tranche(self, scaled: ScaledExitOrder, tranche_idx: int) -> None:
        """Execute a market sell for a take-profit tranche."""
        tranche = scaled.tranches[tranche_idx]
        if tranche.filled:
            return

        sell_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=scaled.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=tranche.quantity,
        )
        tranche.order_id = sell_order.order_id
        self._exit_sell_to_scaled[sell_order.order_id] = (scaled.scaled_order_id, tranche_idx)

        try:
            await self._exec.submit_order(sell_order)
            self._log.info(
                "scaled exit tranche submitted",
                scaled_order_id=scaled.scaled_order_id,
                tranche_idx=tranche_idx,
                price=str(tranche.price),
                quantity=str(tranche.quantity),
            )
        except Exception as exc:
            self._log.error("scaled exit tranche failed", error=str(exc))

    async def _adjust_exit_stop_quantity(self, scaled: ScaledExitOrder) -> None:
        """Adjust resting stop-loss quantity for remaining position."""
        if not scaled.stop_loss_order_id or not scaled.stop_loss_price:
            return

        old_order_id = scaled.stop_loss_order_id

        # Cancel old stop and place new one with adjusted quantity
        try:
            await self._exec.cancel_order(old_order_id)
        except Exception as exc:
            self._log.warning("failed to cancel old stop for adjustment", error=str(exc))
            return

        new_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=scaled.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=scaled.remaining_quantity,
            stop_price=float(scaled.stop_loss_price),
        )

        try:
            await self._exec.submit_order(new_order)
            scaled.stop_loss_order_id = new_order.order_id
            self._log.info(
                "stop-loss adjusted for remaining quantity",
                scaled_order_id=scaled.scaled_order_id,
                new_quantity=str(scaled.remaining_quantity),
            )
        except Exception as exc:
            self._log.error("stop-loss adjustment failed", error=str(exc))

    # ── Internal: Scaled Entries ───────────────────────────────────────

    async def _place_entry_tranches(self, scaled: ScaledEntryOrder) -> None:
        """Place limit buy orders for all entry tranches."""
        try:
            for i, tranche in enumerate(scaled.tranches):
                buy_order = Order(
                    order_id=str(uuid.uuid4()),
                    symbol=scaled.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=tranche.quantity,
                    limit_price=float(tranche.price),
                )
                tranche.order_id = buy_order.order_id
                self._entry_buy_to_scaled[buy_order.order_id] = (scaled.scaled_order_id, i)
                await self._exec.submit_order(buy_order)

            scaled.state = ScaledOrderState.ACTIVE
            await self._bus.publish(ScaledOrderChannel.SCALED_ENTRY_CREATED, {
                "scaled_order_id": scaled.scaled_order_id,
                "symbol": scaled.symbol,
                "tranches": len(scaled.tranches),
            })
        except Exception as exc:
            self._log.error("scaled entry placement failed", error=str(exc))
            scaled.state = ScaledOrderState.ERROR
            scaled.completed_at = datetime.now(timezone.utc)
            await self._bus.publish(ScaledOrderChannel.SCALED_ORDER_ERROR, {
                "scaled_order_id": scaled.scaled_order_id,
                "error": str(exc),
            })

    async def _adjust_entry_stop(self, scaled: ScaledEntryOrder) -> None:
        """Place or adjust stop-loss for filled entry quantity."""
        if not scaled.stop_loss_price:
            return

        # Cancel existing stop if any
        if scaled.stop_loss_order_id:
            try:
                await self._exec.cancel_order(scaled.stop_loss_order_id)
            except Exception:
                pass
            old_id = scaled.stop_loss_order_id
            self._entry_stop_to_scaled.pop(old_id, None)

        # Place new stop for total filled quantity
        stop_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=scaled.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=scaled.filled_quantity,
            stop_price=float(scaled.stop_loss_price),
        )
        scaled.stop_loss_order_id = stop_order.order_id
        self._entry_stop_to_scaled[stop_order.order_id] = scaled.scaled_order_id

        try:
            await self._exec.submit_order(stop_order)
            self._log.info(
                "entry stop-loss placed/adjusted",
                scaled_order_id=scaled.scaled_order_id,
                quantity=str(scaled.filled_quantity),
            )
        except Exception as exc:
            self._log.error("entry stop-loss placement failed", error=str(exc))
