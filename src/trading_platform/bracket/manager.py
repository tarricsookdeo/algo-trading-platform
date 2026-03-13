"""BracketOrderManager orchestrates synthetic bracket order lifecycle.

Listens to execution events and quote data to manage the entry → stop-loss → take-profit
lifecycle. The stop-loss rests as a live order on the exchange; take-profit is monitored
by the framework and triggered when the bid price reaches the target.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from trading_platform.adapters.base import ExecAdapter
from trading_platform.bracket.enums import TERMINAL_STATES, BracketChannel, BracketState
from trading_platform.bracket.models import BracketOrder
from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Order, QuoteTick
from trading_platform.orders.scaled import ScaledOrderChannel, ScaledOrderManager
from trading_platform.orders.trailing_stop import TrailingStopChannel, TrailingStopManager


class BracketOrderManager:
    """Manages the lifecycle of synthetic bracket orders.

    Coordinates entry, stop-loss, and take-profit legs via event bus
    subscriptions and the execution adapter.
    """

    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None) -> None:
        self._bus = event_bus
        self._exec = exec_adapter
        self._log = get_logger("bracket.manager")
        self._brackets: dict[str, BracketOrder] = {}
        # Reverse lookups: child order ID → bracket ID
        self._entry_to_bracket: dict[str, str] = {}
        self._stop_to_bracket: dict[str, str] = {}
        self._tp_to_bracket: dict[str, str] = {}
        # Symbols being monitored for take-profit
        self._monitored_symbols: set[str] = set()
        # Sub-managers for trailing stops and scaled exits
        self._trailing_stop_mgr = TrailingStopManager(event_bus, exec_adapter)
        self._scaled_order_mgr = ScaledOrderManager(event_bus, exec_adapter)
        # Reverse lookups: sub-component ID → bracket ID
        self._trailing_to_bracket: dict[str, str] = {}
        self._scaled_to_bracket: dict[str, str] = {}

    # ── Public API ─────────────────────────────────────────────────────

    async def submit_bracket_order(
        self,
        symbol: str,
        quantity: Decimal,
        entry_type: OrderType,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        entry_limit_price: Decimal | None = None,
        trailing_stop: bool = False,
        trail_amount: Decimal | None = None,
        trail_percent: Decimal | None = None,
        take_profit_levels: list[tuple[Decimal, Decimal]] | None = None,
    ) -> BracketOrder:
        """Submit a new bracket order.

        Args:
            symbol: Equity ticker.
            quantity: Number of shares.
            entry_type: MARKET or LIMIT.
            stop_loss_price: Price for resting stop-loss order.
            take_profit_price: Bid price level that triggers take-profit.
            entry_limit_price: Required if entry_type is LIMIT.
            trailing_stop: If True, use trailing stop instead of fixed stop-loss.
            trail_amount: Absolute dollar trail (requires trailing_stop=True).
            trail_percent: Percentage trail as decimal (requires trailing_stop=True).
            take_profit_levels: List of (price, quantity_percent) tuples for scaled exits.

        Returns:
            The created BracketOrder instance.

        Raises:
            ValueError: If parameters are invalid.
            RuntimeError: If no execution adapter is configured.
        """
        if not self._exec:
            raise RuntimeError("No execution adapter configured")

        # Validate
        if entry_type == OrderType.LIMIT and entry_limit_price is None:
            raise ValueError("entry_limit_price required for LIMIT entry")
        if stop_loss_price >= take_profit_price:
            raise ValueError("stop_loss_price must be less than take_profit_price")
        if entry_type == OrderType.LIMIT and entry_limit_price is not None:
            if stop_loss_price >= entry_limit_price:
                raise ValueError("stop_loss_price must be less than entry_limit_price")
            if entry_limit_price >= take_profit_price:
                raise ValueError("entry_limit_price must be less than take_profit_price")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if trailing_stop:
            if trail_amount is None and trail_percent is None:
                raise ValueError("trailing_stop requires trail_amount or trail_percent")
            if trail_amount is not None and trail_percent is not None:
                raise ValueError("Provide trail_amount or trail_percent, not both")

        bracket_id = str(uuid.uuid4())
        bracket = BracketOrder(
            bracket_id=bracket_id,
            symbol=symbol,
            quantity=quantity,
            entry_type=entry_type,
            entry_limit_price=entry_limit_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_stop=trailing_stop,
            trail_amount=trail_amount,
            trail_percent=trail_percent,
            take_profit_levels=take_profit_levels,
        )
        self._brackets[bracket_id] = bracket

        # Place entry order
        await self._place_entry(bracket)
        return bracket

    def get_bracket(self, bracket_id: str) -> BracketOrder | None:
        """Get a bracket order by ID."""
        return self._brackets.get(bracket_id)

    def get_active_brackets(self) -> list[BracketOrder]:
        """Return all non-terminal bracket orders."""
        return [b for b in self._brackets.values() if b.state not in TERMINAL_STATES]

    def get_all_brackets(self) -> list[BracketOrder]:
        """Return all bracket orders."""
        return list(self._brackets.values())

    async def cancel_bracket(self, bracket_id: str) -> bool:
        """Cancel a bracket order. Cancels any active child orders."""
        bracket = self._brackets.get(bracket_id)
        if not bracket or bracket.state in TERMINAL_STATES:
            return False

        if bracket.state == BracketState.ENTRY_PLACED and bracket.entry_order_id:
            try:
                await self._exec.cancel_order(bracket.entry_order_id)
            except Exception as exc:
                self._log.warning("failed to cancel entry order", bracket_id=bracket_id, error=str(exc))

        if bracket.state in (BracketState.STOP_LOSS_PLACED, BracketState.MONITORING):
            # Cancel trailing stop if active
            if bracket.trailing_stop_id:
                await self._trailing_stop_mgr.cancel_trailing_stop(bracket.trailing_stop_id)
            elif bracket.stop_loss_order_id:
                try:
                    await self._exec.cancel_order(bracket.stop_loss_order_id)
                except Exception as exc:
                    self._log.warning("failed to cancel stop-loss order", bracket_id=bracket_id, error=str(exc))

        await self._transition(bracket, BracketState.CANCELED)
        return True

    # ── Event Wiring ───────────────────────────────────────────────────

    async def wire_events(self) -> None:
        """Subscribe to event bus channels for bracket management."""
        await self._bus.subscribe("execution.order.filled", self._on_order_filled)
        await self._bus.subscribe("execution.order.cancelled", self._on_order_cancelled)
        await self._bus.subscribe("execution.order.rejected", self._on_order_rejected)
        await self._bus.subscribe("execution.order.partially_filled", self._on_order_partially_filled)
        await self._bus.subscribe("quote", self._on_quote)
        # Wire sub-managers
        await self._trailing_stop_mgr.wire_events()
        await self._scaled_order_mgr.wire_events()
        # Subscribe to sub-manager completion events
        await self._bus.subscribe(
            TrailingStopChannel.TRAILING_STOP_COMPLETED, self._on_trailing_stop_completed,
        )
        await self._bus.subscribe(
            TrailingStopChannel.TRAILING_STOP_ERROR, self._on_trailing_stop_error,
        )
        await self._bus.subscribe(
            ScaledOrderChannel.SCALED_EXIT_COMPLETED, self._on_scaled_exit_completed,
        )
        await self._bus.subscribe(
            ScaledOrderChannel.SCALED_EXIT_STOPPED_OUT, self._on_scaled_exit_stopped_out,
        )

    async def unwire_events(self) -> None:
        """Unsubscribe from event bus channels."""
        await self._bus.unsubscribe("execution.order.filled", self._on_order_filled)
        await self._bus.unsubscribe("execution.order.cancelled", self._on_order_cancelled)
        await self._bus.unsubscribe("execution.order.rejected", self._on_order_rejected)
        await self._bus.unsubscribe("execution.order.partially_filled", self._on_order_partially_filled)
        await self._bus.unsubscribe("quote", self._on_quote)
        await self._trailing_stop_mgr.unwire_events()
        await self._scaled_order_mgr.unwire_events()
        await self._bus.unsubscribe(
            TrailingStopChannel.TRAILING_STOP_COMPLETED, self._on_trailing_stop_completed,
        )
        await self._bus.unsubscribe(
            TrailingStopChannel.TRAILING_STOP_ERROR, self._on_trailing_stop_error,
        )
        await self._bus.unsubscribe(
            ScaledOrderChannel.SCALED_EXIT_COMPLETED, self._on_scaled_exit_completed,
        )
        await self._bus.unsubscribe(
            ScaledOrderChannel.SCALED_EXIT_STOPPED_OUT, self._on_scaled_exit_stopped_out,
        )

    # ── Event Handlers ─────────────────────────────────────────────────

    async def _on_order_filled(self, channel: str, event: Any) -> None:
        """Handle ORDER_FILLED events from the execution adapter."""
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id:
            return

        # Entry fill
        if order_id in self._entry_to_bracket:
            bracket_id = self._entry_to_bracket[order_id]
            bracket = self._brackets.get(bracket_id)
            if bracket and bracket.state == BracketState.ENTRY_PLACED:
                fill_price = event.get("fill_price") or event.get("avg_price")
                if fill_price is not None:
                    bracket.entry_fill_price = Decimal(str(fill_price))
                bracket.entry_filled_at = datetime.now(timezone.utc)
                await self._transition(bracket, BracketState.ENTRY_FILLED)
                await self._bus.publish(BracketChannel.BRACKET_ENTRY_FILLED, {
                    "bracket_id": bracket_id,
                    "symbol": bracket.symbol,
                    "quantity": bracket.quantity,
                    "fill_price": str(bracket.entry_fill_price),
                })
                # Place stop-loss
                await self._place_stop_loss(bracket)
            return

        # Stop-loss fill
        if order_id in self._stop_to_bracket:
            bracket_id = self._stop_to_bracket[order_id]
            bracket = self._brackets.get(bracket_id)
            if bracket and bracket.state in (
                BracketState.STOP_LOSS_PLACED,
                BracketState.MONITORING,
                BracketState.TAKE_PROFIT_TRIGGERED,
            ):
                fill_price = event.get("fill_price") or event.get("avg_price")
                if fill_price is not None:
                    bracket.exit_fill_price = Decimal(str(fill_price))
                await self._transition(bracket, BracketState.STOPPED_OUT)
                await self._bus.publish(BracketChannel.BRACKET_STOPPED_OUT, {
                    "bracket_id": bracket_id,
                    "symbol": bracket.symbol,
                    "exit_price": str(bracket.exit_fill_price),
                })
                self._monitored_symbols.discard(bracket.symbol)
            return

        # Take-profit market sell fill
        if order_id in self._tp_to_bracket:
            bracket_id = self._tp_to_bracket[order_id]
            bracket = self._brackets.get(bracket_id)
            if bracket and bracket.state == BracketState.TAKE_PROFIT_TRIGGERED:
                fill_price = event.get("fill_price") or event.get("avg_price")
                if fill_price is not None:
                    bracket.exit_fill_price = Decimal(str(fill_price))
                await self._transition(bracket, BracketState.TAKE_PROFIT_FILLED)
                await self._bus.publish(BracketChannel.BRACKET_TAKE_PROFIT_FILLED, {
                    "bracket_id": bracket_id,
                    "symbol": bracket.symbol,
                    "exit_price": str(bracket.exit_fill_price),
                })
            return

    async def _on_order_cancelled(self, channel: str, event: Any) -> None:
        """Handle ORDER_CANCELLED events."""
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id:
            return

        # Entry cancelled
        if order_id in self._entry_to_bracket:
            bracket_id = self._entry_to_bracket[order_id]
            bracket = self._brackets.get(bracket_id)
            if bracket and bracket.state == BracketState.ENTRY_PLACED:
                await self._transition(bracket, BracketState.CANCELED)
                await self._bus.publish(BracketChannel.BRACKET_CANCELED, {
                    "bracket_id": bracket_id,
                    "reason": "entry_cancelled",
                })
            return

        # Stop-loss cancelled (expected during take-profit flow)
        if order_id in self._stop_to_bracket:
            bracket_id = self._stop_to_bracket[order_id]
            bracket = self._brackets.get(bracket_id)
            if bracket and bracket.state == BracketState.TAKE_PROFIT_TRIGGERED:
                # Stop cancelled as expected — now place market sell
                await self._place_take_profit_sell(bracket)
            elif bracket and bracket.state == BracketState.CANCELED:
                # Stop cancelled as part of bracket cancel — already handled
                pass
            return

    async def _on_order_rejected(self, channel: str, event: Any) -> None:
        """Handle ORDER_REJECTED events."""
        order_id = event.get("order_id") if isinstance(event, dict) else None
        if not order_id:
            return

        if order_id in self._entry_to_bracket:
            bracket_id = self._entry_to_bracket[order_id]
            bracket = self._brackets.get(bracket_id)
            if bracket and bracket.state == BracketState.ENTRY_PLACED:
                await self._transition(bracket, BracketState.ENTRY_REJECTED)
                await self._bus.publish(BracketChannel.BRACKET_CANCELED, {
                    "bracket_id": bracket_id,
                    "reason": "entry_rejected",
                })

    async def _on_order_partially_filled(self, channel: str, event: Any) -> None:
        """Handle partial fills — we wait for full fill before placing stop."""
        # Intentionally no-op: we only act on full fill
        pass

    async def _on_quote(self, channel: str, event: Any) -> None:
        """Monitor bid prices for take-profit triggers."""
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

        for bracket in self._brackets.values():
            if (
                bracket.symbol == symbol
                and bracket.state == BracketState.MONITORING
                and bid_price >= bracket.take_profit_price
            ):
                self._log.info(
                    "take-profit triggered",
                    bracket_id=bracket.bracket_id,
                    bid=str(bid_price),
                    target=str(bracket.take_profit_price),
                )
                await self._trigger_take_profit(bracket)

    # ── Internal Order Placement ───────────────────────────────────────

    async def _place_entry(self, bracket: BracketOrder) -> None:
        """Place the entry order (market or limit buy)."""
        entry_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=bracket.symbol,
            side=OrderSide.BUY,
            order_type=bracket.entry_type,
            quantity=bracket.quantity,
            limit_price=float(bracket.entry_limit_price) if bracket.entry_limit_price else None,
        )
        bracket.entry_order_id = entry_order.order_id
        self._entry_to_bracket[entry_order.order_id] = bracket.bracket_id

        try:
            await self._exec.submit_order(entry_order)
            await self._transition(bracket, BracketState.ENTRY_PLACED)
        except Exception as exc:
            self._log.error("entry order placement failed", bracket_id=bracket.bracket_id, error=str(exc))
            await self._transition(bracket, BracketState.ERROR)
            await self._bus.publish(BracketChannel.BRACKET_ERROR, {
                "bracket_id": bracket.bracket_id,
                "error": f"entry placement failed: {exc}",
            })

    async def _place_stop_loss(self, bracket: BracketOrder) -> None:
        """Place the resting stop-loss order after entry fill.

        If trailing_stop is True, delegates to TrailingStopManager.
        If take_profit_levels is set, delegates take-profit monitoring to ScaledOrderManager.
        """
        # Trailing stop path
        if bracket.trailing_stop:
            try:
                current_price = bracket.entry_fill_price or bracket.stop_loss_price
                ts = await self._trailing_stop_mgr.create_trailing_stop(
                    symbol=bracket.symbol,
                    quantity=bracket.quantity,
                    current_price=current_price,
                    trail_amount=bracket.trail_amount,
                    trail_percent=bracket.trail_percent,
                )
                bracket.trailing_stop_id = ts.trailing_stop_id
                self._trailing_to_bracket[ts.trailing_stop_id] = bracket.bracket_id
                await self._transition(bracket, BracketState.STOP_LOSS_PLACED)
                await self._bus.publish(BracketChannel.BRACKET_STOP_PLACED, {
                    "bracket_id": bracket.bracket_id,
                    "trailing_stop_id": ts.trailing_stop_id,
                    "stop_loss_price": str(ts.current_stop_price),
                })
            except Exception as exc:
                self._log.error(
                    "trailing stop placement failed — position unprotected!",
                    bracket_id=bracket.bracket_id,
                    error=str(exc),
                )
                await self._transition(bracket, BracketState.ERROR)
                await self._bus.publish(BracketChannel.BRACKET_ERROR, {
                    "bracket_id": bracket.bracket_id,
                    "error": f"trailing stop placement failed: {exc}",
                })
                return
        else:
            # Fixed stop-loss path
            stop_order = Order(
                order_id=str(uuid.uuid4()),
                symbol=bracket.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.STOP,
                quantity=bracket.quantity,
                stop_price=float(bracket.stop_loss_price),
            )
            bracket.stop_loss_order_id = stop_order.order_id
            self._stop_to_bracket[stop_order.order_id] = bracket.bracket_id

            try:
                await self._exec.submit_order(stop_order)
                await self._transition(bracket, BracketState.STOP_LOSS_PLACED)
                await self._bus.publish(BracketChannel.BRACKET_STOP_PLACED, {
                    "bracket_id": bracket.bracket_id,
                    "stop_loss_order_id": stop_order.order_id,
                    "stop_loss_price": str(bracket.stop_loss_price),
                })
            except Exception as exc:
                self._log.error(
                    "stop-loss placement failed — position unprotected!",
                    bracket_id=bracket.bracket_id,
                    error=str(exc),
                )
                await self._transition(bracket, BracketState.ERROR)
                await self._bus.publish(BracketChannel.BRACKET_ERROR, {
                    "bracket_id": bracket.bracket_id,
                    "error": f"stop-loss placement failed: {exc}",
                })
                return

        # Scaled exits path: delegate take-profit monitoring to ScaledOrderManager
        if bracket.take_profit_levels:
            try:
                scaled = await self._scaled_order_mgr.create_scaled_exit(
                    symbol=bracket.symbol,
                    total_quantity=bracket.quantity,
                    take_profit_levels=bracket.take_profit_levels,
                    stop_loss_price=bracket.stop_loss_price,
                )
                bracket.scaled_exit_id = scaled.scaled_id
                self._scaled_to_bracket[scaled.scaled_id] = bracket.bracket_id
                # Scaled manager handles its own stop and monitoring
                await self._transition(bracket, BracketState.MONITORING)
            except Exception as exc:
                self._log.error(
                    "scaled exit setup failed",
                    bracket_id=bracket.bracket_id,
                    error=str(exc),
                )
                await self._transition(bracket, BracketState.ERROR)
                await self._bus.publish(BracketChannel.BRACKET_ERROR, {
                    "bracket_id": bracket.bracket_id,
                    "error": f"scaled exit setup failed: {exc}",
                })
        else:
            # Standard single take-profit monitoring
            self._monitored_symbols.add(bracket.symbol)
            await self._transition(bracket, BracketState.MONITORING)

    async def _trigger_take_profit(self, bracket: BracketOrder) -> None:
        """Trigger take-profit: cancel stop-loss, then place market sell."""
        await self._transition(bracket, BracketState.TAKE_PROFIT_TRIGGERED)
        await self._bus.publish(BracketChannel.BRACKET_TAKE_PROFIT_TRIGGERED, {
            "bracket_id": bracket.bracket_id,
            "symbol": bracket.symbol,
        })
        self._monitored_symbols.discard(bracket.symbol)

        # Cancel the resting stop-loss
        try:
            await self._exec.cancel_order(bracket.stop_loss_order_id)
            # Wait for cancellation confirmation via _on_order_cancelled
        except Exception as exc:
            # Cancel failed — stop may have already filled
            self._log.warning(
                "stop-loss cancel failed during take-profit, treating as stopped out",
                bracket_id=bracket.bracket_id,
                error=str(exc),
            )
            await self._transition(bracket, BracketState.STOPPED_OUT)
            await self._bus.publish(BracketChannel.BRACKET_STOPPED_OUT, {
                "bracket_id": bracket.bracket_id,
                "symbol": bracket.symbol,
                "reason": "stop_cancel_failed",
            })

    async def _place_take_profit_sell(self, bracket: BracketOrder) -> None:
        """Place a market sell order for the take-profit exit."""
        sell_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=bracket.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=bracket.quantity,
        )
        bracket.take_profit_order_id = sell_order.order_id
        self._tp_to_bracket[sell_order.order_id] = bracket.bracket_id

        try:
            await self._exec.submit_order(sell_order)
        except Exception as exc:
            self._log.error("take-profit sell failed", bracket_id=bracket.bracket_id, error=str(exc))
            await self._transition(bracket, BracketState.ERROR)
            await self._bus.publish(BracketChannel.BRACKET_ERROR, {
                "bracket_id": bracket.bracket_id,
                "error": f"take-profit sell failed: {exc}",
            })

    # ── Sub-Manager Event Handlers ────────────────────────────────────

    async def _on_trailing_stop_completed(self, channel: str, event: Any) -> None:
        """Handle trailing stop completion → bracket is stopped out."""
        ts_id = event.get("trailing_stop_id") if isinstance(event, dict) else None
        if not ts_id or ts_id not in self._trailing_to_bracket:
            return
        bracket_id = self._trailing_to_bracket[ts_id]
        bracket = self._brackets.get(bracket_id)
        if not bracket or bracket.state in TERMINAL_STATES:
            return
        exit_price = event.get("exit_price")
        if exit_price is not None:
            bracket.exit_fill_price = Decimal(str(exit_price))
        self._monitored_symbols.discard(bracket.symbol)
        await self._transition(bracket, BracketState.STOPPED_OUT)
        await self._bus.publish(BracketChannel.BRACKET_STOPPED_OUT, {
            "bracket_id": bracket_id,
            "symbol": bracket.symbol,
            "exit_price": str(bracket.exit_fill_price),
        })

    async def _on_trailing_stop_error(self, channel: str, event: Any) -> None:
        """Handle trailing stop error → bracket enters ERROR state."""
        ts_id = event.get("trailing_stop_id") if isinstance(event, dict) else None
        if not ts_id or ts_id not in self._trailing_to_bracket:
            return
        bracket_id = self._trailing_to_bracket[ts_id]
        bracket = self._brackets.get(bracket_id)
        if not bracket or bracket.state in TERMINAL_STATES:
            return
        await self._transition(bracket, BracketState.ERROR)
        await self._bus.publish(BracketChannel.BRACKET_ERROR, {
            "bracket_id": bracket_id,
            "error": event.get("error", "trailing stop error"),
        })

    async def _on_scaled_exit_completed(self, channel: str, event: Any) -> None:
        """Handle scaled exit completion → bracket take-profit filled."""
        scaled_id = event.get("scaled_id") if isinstance(event, dict) else None
        if not scaled_id or scaled_id not in self._scaled_to_bracket:
            return
        bracket_id = self._scaled_to_bracket[scaled_id]
        bracket = self._brackets.get(bracket_id)
        if not bracket or bracket.state in TERMINAL_STATES:
            return
        # Cancel the bracket's own stop-loss if present (trailing or fixed)
        if bracket.trailing_stop_id:
            await self._trailing_stop_mgr.cancel_trailing_stop(bracket.trailing_stop_id)
        elif bracket.stop_loss_order_id:
            try:
                await self._exec.cancel_order(bracket.stop_loss_order_id)
            except Exception:
                pass
        await self._transition(bracket, BracketState.TAKE_PROFIT_FILLED)
        await self._bus.publish(BracketChannel.BRACKET_TAKE_PROFIT_FILLED, {
            "bracket_id": bracket_id,
            "symbol": bracket.symbol,
        })

    async def _on_scaled_exit_stopped_out(self, channel: str, event: Any) -> None:
        """Handle scaled exit stopped out → bracket is stopped out."""
        scaled_id = event.get("scaled_id") if isinstance(event, dict) else None
        if not scaled_id or scaled_id not in self._scaled_to_bracket:
            return
        bracket_id = self._scaled_to_bracket[scaled_id]
        bracket = self._brackets.get(bracket_id)
        if not bracket or bracket.state in TERMINAL_STATES:
            return
        # Cancel the bracket's own trailing stop if present
        if bracket.trailing_stop_id:
            await self._trailing_stop_mgr.cancel_trailing_stop(bracket.trailing_stop_id)
        self._monitored_symbols.discard(bracket.symbol)
        await self._transition(bracket, BracketState.STOPPED_OUT)
        await self._bus.publish(BracketChannel.BRACKET_STOPPED_OUT, {
            "bracket_id": bracket_id,
            "symbol": bracket.symbol,
            "remaining_quantity": event.get("remaining_quantity"),
        })

    # ── State Machine ──────────────────────────────────────────────────

    async def _transition(self, bracket: BracketOrder, new_state: BracketState) -> None:
        """Transition a bracket to a new state, emitting a state change event."""
        old_state = bracket.state
        bracket.state = new_state
        if new_state in TERMINAL_STATES:
            bracket.completed_at = datetime.now(timezone.utc)
        self._log.info(
            "bracket state change",
            bracket_id=bracket.bracket_id,
            from_state=str(old_state),
            to_state=str(new_state),
        )
        await self._bus.publish(BracketChannel.BRACKET_STATE_CHANGE, {
            "bracket_id": bracket.bracket_id,
            "symbol": bracket.symbol,
            "from_state": str(old_state),
            "to_state": str(new_state),
        })
