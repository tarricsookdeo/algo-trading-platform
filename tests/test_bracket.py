"""Comprehensive tests for the bracket order module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_platform.bracket.enums import TERMINAL_STATES, BracketChannel, BracketState
from trading_platform.bracket.manager import BracketOrderManager
from trading_platform.bracket.models import BracketOrder
from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.models import Order, QuoteTick


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_exec():
    exec_adapter = AsyncMock()
    exec_adapter.submit_order = AsyncMock(return_value=None)
    exec_adapter.cancel_order = AsyncMock(return_value=None)
    return exec_adapter


@pytest.fixture
def manager(bus, mock_exec):
    return BracketOrderManager(event_bus=bus, exec_adapter=mock_exec)


@pytest.fixture
async def wired_manager(manager, bus):
    await manager.wire_events()
    yield manager
    await manager.unwire_events()


# ── Helpers ───────────────────────────────────────────────────────────


async def submit_default_market_bracket(manager):
    """Submit a standard market bracket order for testing."""
    return await manager.submit_bracket_order(
        symbol="AAPL",
        quantity=10,
        entry_type=OrderType.MARKET,
        stop_loss_price=Decimal("140"),
        take_profit_price=Decimal("160"),
    )


async def fill_entry(bus, bracket):
    """Simulate entry order fill."""
    await bus.publish("execution.order.filled", {
        "order_id": bracket.entry_order_id,
        "fill_price": "150.00",
    })


async def fill_stop_loss(bus, bracket):
    """Simulate stop-loss fill."""
    await bus.publish("execution.order.filled", {
        "order_id": bracket.stop_loss_order_id,
        "fill_price": "140.00",
    })


async def cancel_stop_loss(bus, bracket):
    """Simulate stop-loss cancellation confirmation."""
    await bus.publish("execution.order.cancelled", {
        "order_id": bracket.stop_loss_order_id,
    })


async def fill_take_profit(bus, bracket):
    """Simulate take-profit market sell fill."""
    await bus.publish("execution.order.filled", {
        "order_id": bracket.take_profit_order_id,
        "fill_price": "161.00",
    })


async def send_quote(bus, symbol, bid_price):
    """Publish a quote event with given bid price."""
    await bus.publish("quote", {
        "symbol": symbol,
        "bid_price": bid_price,
        "ask_price": bid_price + 0.01,
        "bid_size": 100,
        "ask_size": 100,
        "timestamp": "2026-01-15T10:00:00Z",
    })


# ── Model Tests ───────────────────────────────────────────────────────


class TestBracketOrderModel:
    def test_create_bracket_order(self):
        bracket = BracketOrder(
            bracket_id="test-1",
            symbol="AAPL",
            quantity=10,
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
        )
        assert bracket.state == BracketState.PENDING_ENTRY
        assert bracket.entry_order_id is None
        assert bracket.stop_loss_order_id is None
        assert bracket.take_profit_order_id is None
        assert bracket.created_at is not None

    def test_bracket_order_with_limit(self):
        bracket = BracketOrder(
            bracket_id="test-2",
            symbol="MSFT",
            quantity=5,
            entry_type=OrderType.LIMIT,
            entry_limit_price=Decimal("150"),
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
        )
        assert bracket.entry_limit_price == Decimal("150")
        assert bracket.entry_type == OrderType.LIMIT


class TestBracketEnums:
    def test_terminal_states(self):
        assert BracketState.TAKE_PROFIT_FILLED in TERMINAL_STATES
        assert BracketState.STOPPED_OUT in TERMINAL_STATES
        assert BracketState.CANCELED in TERMINAL_STATES
        assert BracketState.ENTRY_REJECTED in TERMINAL_STATES
        assert BracketState.ERROR in TERMINAL_STATES
        assert BracketState.MONITORING not in TERMINAL_STATES


# ── Validation Tests ──────────────────────────────────────────────────


class TestBracketValidation:
    @pytest.mark.asyncio
    async def test_no_exec_adapter(self, bus):
        mgr = BracketOrderManager(event_bus=bus, exec_adapter=None)
        with pytest.raises(RuntimeError, match="No execution adapter"):
            await mgr.submit_bracket_order(
                symbol="AAPL", quantity=10, entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("140"), take_profit_price=Decimal("160"),
            )

    @pytest.mark.asyncio
    async def test_limit_without_price(self, manager):
        with pytest.raises(ValueError, match="entry_limit_price required"):
            await manager.submit_bracket_order(
                symbol="AAPL", quantity=10, entry_type=OrderType.LIMIT,
                stop_loss_price=Decimal("140"), take_profit_price=Decimal("160"),
            )

    @pytest.mark.asyncio
    async def test_stop_above_take_profit(self, manager):
        with pytest.raises(ValueError, match="stop_loss_price must be less than take_profit_price"):
            await manager.submit_bracket_order(
                symbol="AAPL", quantity=10, entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("170"), take_profit_price=Decimal("160"),
            )

    @pytest.mark.asyncio
    async def test_stop_equals_take_profit(self, manager):
        with pytest.raises(ValueError, match="stop_loss_price must be less than take_profit_price"):
            await manager.submit_bracket_order(
                symbol="AAPL", quantity=10, entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("160"), take_profit_price=Decimal("160"),
            )

    @pytest.mark.asyncio
    async def test_limit_price_validation(self, manager):
        with pytest.raises(ValueError, match="stop_loss_price must be less than entry_limit_price"):
            await manager.submit_bracket_order(
                symbol="AAPL", quantity=10, entry_type=OrderType.LIMIT,
                entry_limit_price=Decimal("140"),
                stop_loss_price=Decimal("145"), take_profit_price=Decimal("160"),
            )

    @pytest.mark.asyncio
    async def test_limit_above_take_profit(self, manager):
        with pytest.raises(ValueError, match="entry_limit_price must be less than take_profit_price"):
            await manager.submit_bracket_order(
                symbol="AAPL", quantity=10, entry_type=OrderType.LIMIT,
                entry_limit_price=Decimal("165"),
                stop_loss_price=Decimal("140"), take_profit_price=Decimal("160"),
            )

    @pytest.mark.asyncio
    async def test_zero_quantity(self, manager):
        with pytest.raises(ValueError, match="quantity must be positive"):
            await manager.submit_bracket_order(
                symbol="AAPL", quantity=0, entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("140"), take_profit_price=Decimal("160"),
            )

    @pytest.mark.asyncio
    async def test_negative_quantity(self, manager):
        with pytest.raises(ValueError, match="quantity must be positive"):
            await manager.submit_bracket_order(
                symbol="AAPL", quantity=-5, entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("140"), take_profit_price=Decimal("160"),
            )


# ── Full Lifecycle: Stop-Loss Path ────────────────────────────────────


class TestStopLossLifecycle:
    @pytest.mark.asyncio
    async def test_market_entry_to_stop_loss(self, wired_manager, bus, mock_exec):
        """Full lifecycle: market entry → fill → stop-loss placed → stop-loss hit."""
        bracket = await submit_default_market_bracket(wired_manager)
        assert bracket.state == BracketState.ENTRY_PLACED
        assert bracket.entry_order_id is not None
        assert mock_exec.submit_order.call_count == 1

        # Verify entry order is a market buy
        entry_order = mock_exec.submit_order.call_args[0][0]
        assert entry_order.side == OrderSide.BUY
        assert entry_order.order_type == OrderType.MARKET
        assert entry_order.quantity == Decimal("10")

        # Simulate entry fill
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING
        assert bracket.entry_fill_price == Decimal("150.00")
        assert bracket.entry_filled_at is not None
        assert mock_exec.submit_order.call_count == 2

        # Verify stop-loss order
        stop_order = mock_exec.submit_order.call_args[0][0]
        assert stop_order.side == OrderSide.SELL
        assert stop_order.order_type == OrderType.STOP
        assert stop_order.stop_price == 140.0

        # Simulate stop-loss fill
        await fill_stop_loss(bus, bracket)
        assert bracket.state == BracketState.STOPPED_OUT
        assert bracket.exit_fill_price == Decimal("140.00")
        assert bracket.completed_at is not None

    @pytest.mark.asyncio
    async def test_limit_entry_to_stop_loss(self, wired_manager, bus, mock_exec):
        """Limit entry → fill → stop-loss hit."""
        bracket = await wired_manager.submit_bracket_order(
            symbol="MSFT",
            quantity=20,
            entry_type=OrderType.LIMIT,
            entry_limit_price=Decimal("150"),
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
        )
        assert bracket.state == BracketState.ENTRY_PLACED

        # Verify limit order
        entry_order = mock_exec.submit_order.call_args[0][0]
        assert entry_order.order_type == OrderType.LIMIT
        assert entry_order.limit_price == 150.0

        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING

        await fill_stop_loss(bus, bracket)
        assert bracket.state == BracketState.STOPPED_OUT


# ── Full Lifecycle: Take-Profit Path ─────────────────────────────────


class TestTakeProfitLifecycle:
    @pytest.mark.asyncio
    async def test_market_entry_to_take_profit(self, wired_manager, bus, mock_exec):
        """Full lifecycle: entry → fill → monitoring → bid hits target → cancel stop → market sell."""
        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING

        # Send bid below target — should not trigger
        await send_quote(bus, "AAPL", 155.0)
        assert bracket.state == BracketState.MONITORING

        # Send bid at target — should trigger take-profit
        await send_quote(bus, "AAPL", 160.0)
        assert bracket.state == BracketState.TAKE_PROFIT_TRIGGERED
        mock_exec.cancel_order.assert_called_once_with(bracket.stop_loss_order_id)

        # Confirm stop-loss cancellation
        await cancel_stop_loss(bus, bracket)
        assert bracket.take_profit_order_id is not None
        assert mock_exec.submit_order.call_count == 3  # entry + stop + TP sell

        # Verify market sell
        tp_order = mock_exec.submit_order.call_args[0][0]
        assert tp_order.side == OrderSide.SELL
        assert tp_order.order_type == OrderType.MARKET
        assert tp_order.quantity == Decimal("10")

        # Fill take-profit
        await fill_take_profit(bus, bracket)
        assert bracket.state == BracketState.TAKE_PROFIT_FILLED
        assert bracket.exit_fill_price == Decimal("161.00")
        assert bracket.completed_at is not None

    @pytest.mark.asyncio
    async def test_take_profit_bid_above_target(self, wired_manager, bus, mock_exec):
        """Bid above take-profit target should also trigger."""
        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING

        # Bid above target
        await send_quote(bus, "AAPL", 175.0)
        assert bracket.state == BracketState.TAKE_PROFIT_TRIGGERED


# ── Entry Rejection / Cancellation ────────────────────────────────────


class TestEntryFailures:
    @pytest.mark.asyncio
    async def test_entry_rejected(self, wired_manager, bus):
        """Entry order rejected → bracket moves to ENTRY_REJECTED."""
        bracket = await submit_default_market_bracket(wired_manager)
        assert bracket.state == BracketState.ENTRY_PLACED

        await bus.publish("execution.order.rejected", {
            "order_id": bracket.entry_order_id,
        })
        assert bracket.state == BracketState.ENTRY_REJECTED
        assert bracket.completed_at is not None

    @pytest.mark.asyncio
    async def test_entry_cancelled(self, wired_manager, bus):
        """Entry order cancelled → bracket moves to CANCELED."""
        bracket = await submit_default_market_bracket(wired_manager)

        await bus.publish("execution.order.cancelled", {
            "order_id": bracket.entry_order_id,
        })
        assert bracket.state == BracketState.CANCELED

    @pytest.mark.asyncio
    async def test_limit_entry_never_fills(self, wired_manager, bus, mock_exec):
        """Limit order that gets cancelled without filling."""
        bracket = await wired_manager.submit_bracket_order(
            symbol="TSLA",
            quantity=5,
            entry_type=OrderType.LIMIT,
            entry_limit_price=Decimal("200"),
            stop_loss_price=Decimal("190"),
            take_profit_price=Decimal("220"),
        )

        await bus.publish("execution.order.cancelled", {
            "order_id": bracket.entry_order_id,
        })
        assert bracket.state == BracketState.CANCELED
        # Stop-loss should never have been placed
        assert bracket.stop_loss_order_id is None


# ── Partial Fill Waiting ──────────────────────────────────────────────


class TestPartialFills:
    @pytest.mark.asyncio
    async def test_partial_fill_does_not_place_stop(self, wired_manager, bus, mock_exec):
        """Partial fill should NOT trigger stop-loss placement."""
        bracket = await submit_default_market_bracket(wired_manager)

        await bus.publish("execution.order.partially_filled", {
            "order_id": bracket.entry_order_id,
            "filled_quantity": 5,
        })
        # Should still be in ENTRY_PLACED, not ENTRY_FILLED
        assert bracket.state == BracketState.ENTRY_PLACED
        # Only 1 submit call (the entry), no stop-loss yet
        assert mock_exec.submit_order.call_count == 1

    @pytest.mark.asyncio
    async def test_full_fill_after_partial(self, wired_manager, bus, mock_exec):
        """After partial fills, a full fill triggers stop-loss placement."""
        bracket = await submit_default_market_bracket(wired_manager)

        # Partial fill
        await bus.publish("execution.order.partially_filled", {
            "order_id": bracket.entry_order_id,
            "filled_quantity": 5,
        })
        assert bracket.state == BracketState.ENTRY_PLACED

        # Full fill
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING
        assert mock_exec.submit_order.call_count == 2  # entry + stop


# ── Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_stop_cancel_fails_during_take_profit(self, wired_manager, bus, mock_exec):
        """If stop-loss cancel fails, treat as stopped out."""
        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)

        # Make cancel raise an exception
        mock_exec.cancel_order = AsyncMock(side_effect=Exception("cancel failed"))

        await send_quote(bus, "AAPL", 160.0)
        assert bracket.state == BracketState.STOPPED_OUT

    @pytest.mark.asyncio
    async def test_stop_loss_placement_failure(self, wired_manager, bus, mock_exec):
        """Stop-loss placement fails after entry fill → ERROR state."""
        bracket = await submit_default_market_bracket(wired_manager)

        # Entry already placed; now make submit_order fail for the stop-loss
        mock_exec.submit_order = AsyncMock(side_effect=Exception("placement failed"))

        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.ERROR

    @pytest.mark.asyncio
    async def test_stop_fills_during_take_profit_cancel_confirmation(self, wired_manager, bus, mock_exec):
        """Stop-loss fills while take-profit is triggered (race condition)."""
        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)

        # Trigger take-profit
        await send_quote(bus, "AAPL", 160.0)
        assert bracket.state == BracketState.TAKE_PROFIT_TRIGGERED

        # Stop-loss fills before cancel confirmation
        await fill_stop_loss(bus, bracket)
        assert bracket.state == BracketState.STOPPED_OUT

    @pytest.mark.asyncio
    async def test_unrelated_order_events_ignored(self, wired_manager, bus):
        """Events for unrelated order IDs should not affect brackets."""
        bracket = await submit_default_market_bracket(wired_manager)

        await bus.publish("execution.order.filled", {
            "order_id": "unrelated-order-123",
            "fill_price": "999.00",
        })
        assert bracket.state == BracketState.ENTRY_PLACED

    @pytest.mark.asyncio
    async def test_quote_for_unmonitored_symbol(self, wired_manager, bus):
        """Quotes for symbols not in any bracket should be ignored."""
        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)

        # Quote for different symbol
        await send_quote(bus, "GOOG", 5000.0)
        assert bracket.state == BracketState.MONITORING

    @pytest.mark.asyncio
    async def test_quote_before_monitoring(self, wired_manager, bus):
        """Quotes received before bracket is in MONITORING state should be ignored."""
        bracket = await submit_default_market_bracket(wired_manager)
        # Still in ENTRY_PLACED, not MONITORING
        await send_quote(bus, "AAPL", 200.0)
        assert bracket.state == BracketState.ENTRY_PLACED

    @pytest.mark.asyncio
    async def test_entry_placement_failure(self, wired_manager, bus, mock_exec):
        """If entry order submission fails, bracket goes to ERROR."""
        mock_exec.submit_order = AsyncMock(side_effect=Exception("broker down"))
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL", quantity=10, entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"), take_profit_price=Decimal("160"),
        )
        assert bracket.state == BracketState.ERROR


# ── Bracket Management ────────────────────────────────────────────────


class TestBracketManagement:
    @pytest.mark.asyncio
    async def test_get_bracket(self, wired_manager, bus):
        bracket = await submit_default_market_bracket(wired_manager)
        found = wired_manager.get_bracket(bracket.bracket_id)
        assert found is bracket

    @pytest.mark.asyncio
    async def test_get_nonexistent_bracket(self, wired_manager):
        assert wired_manager.get_bracket("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_active_brackets(self, wired_manager, bus):
        b1 = await submit_default_market_bracket(wired_manager)
        b2 = await submit_default_market_bracket(wired_manager)
        active = wired_manager.get_active_brackets()
        assert len(active) == 2

        # Cancel one
        await wired_manager.cancel_bracket(b1.bracket_id)
        active = wired_manager.get_active_brackets()
        assert len(active) == 1
        assert active[0].bracket_id == b2.bracket_id

    @pytest.mark.asyncio
    async def test_get_all_brackets(self, wired_manager, bus):
        b1 = await submit_default_market_bracket(wired_manager)
        b2 = await submit_default_market_bracket(wired_manager)
        await wired_manager.cancel_bracket(b1.bracket_id)
        all_brackets = wired_manager.get_all_brackets()
        assert len(all_brackets) == 2

    @pytest.mark.asyncio
    async def test_cancel_entry_placed(self, wired_manager, bus, mock_exec):
        """Cancel bracket while entry is still pending."""
        bracket = await submit_default_market_bracket(wired_manager)
        result = await wired_manager.cancel_bracket(bracket.bracket_id)
        assert result is True
        assert bracket.state == BracketState.CANCELED
        mock_exec.cancel_order.assert_called_once_with(bracket.entry_order_id)

    @pytest.mark.asyncio
    async def test_cancel_monitoring(self, wired_manager, bus, mock_exec):
        """Cancel bracket while monitoring for take-profit."""
        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING

        result = await wired_manager.cancel_bracket(bracket.bracket_id)
        assert result is True
        assert bracket.state == BracketState.CANCELED
        mock_exec.cancel_order.assert_called_with(bracket.stop_loss_order_id)

    @pytest.mark.asyncio
    async def test_cancel_already_terminal(self, wired_manager, bus):
        """Canceling an already-terminal bracket returns False."""
        bracket = await submit_default_market_bracket(wired_manager)
        await bus.publish("execution.order.rejected", {
            "order_id": bracket.entry_order_id,
        })
        assert bracket.state == BracketState.ENTRY_REJECTED
        result = await wired_manager.cancel_bracket(bracket.bracket_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, wired_manager):
        result = await wired_manager.cancel_bracket("nonexistent")
        assert result is False


# ── Event Emission Tests ──────────────────────────────────────────────


class TestBracketEvents:
    @pytest.mark.asyncio
    async def test_state_change_events(self, wired_manager, bus, mock_exec):
        """State change events are emitted for each transition."""
        state_changes = []

        async def on_state_change(ch, ev):
            state_changes.append(ev)

        await bus.subscribe(BracketChannel.BRACKET_STATE_CHANGE, on_state_change)

        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)
        await fill_stop_loss(bus, bracket)

        # Should have: ENTRY_PLACED, ENTRY_FILLED, STOP_LOSS_PLACED, MONITORING, STOPPED_OUT
        states = [sc["to_state"] for sc in state_changes]
        assert "entry_placed" in states
        assert "entry_filled" in states
        assert "stop_loss_placed" in states
        assert "monitoring" in states
        assert "stopped_out" in states

    @pytest.mark.asyncio
    async def test_entry_filled_event(self, wired_manager, bus):
        """BRACKET_ENTRY_FILLED event is emitted on entry fill."""
        events = []

        async def on_filled(ch, ev):
            events.append(ev)

        await bus.subscribe(BracketChannel.BRACKET_ENTRY_FILLED, on_filled)

        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)

        assert len(events) == 1
        assert events[0]["bracket_id"] == bracket.bracket_id
        assert events[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_stopped_out_event(self, wired_manager, bus):
        """BRACKET_STOPPED_OUT event is emitted on stop-loss fill."""
        events = []

        async def on_stop(ch, ev):
            events.append(ev)

        await bus.subscribe(BracketChannel.BRACKET_STOPPED_OUT, on_stop)

        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)
        await fill_stop_loss(bus, bracket)

        assert len(events) == 1
        assert events[0]["bracket_id"] == bracket.bracket_id

    @pytest.mark.asyncio
    async def test_take_profit_events(self, wired_manager, bus, mock_exec):
        """Take-profit events are emitted correctly."""
        triggered_events = []
        filled_events = []

        async def on_triggered(ch, ev):
            triggered_events.append(ev)

        async def on_filled(ch, ev):
            filled_events.append(ev)

        await bus.subscribe(BracketChannel.BRACKET_TAKE_PROFIT_TRIGGERED, on_triggered)
        await bus.subscribe(BracketChannel.BRACKET_TAKE_PROFIT_FILLED, on_filled)

        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)
        await send_quote(bus, "AAPL", 160.0)

        assert len(triggered_events) == 1

        await cancel_stop_loss(bus, bracket)
        await fill_take_profit(bus, bracket)

        assert len(filled_events) == 1
        assert filled_events[0]["bracket_id"] == bracket.bracket_id


# ── Wire/Unwire Tests ────────────────────────────────────────────────


class TestWiring:
    @pytest.mark.asyncio
    async def test_wire_and_unwire(self, bus, mock_exec):
        mgr = BracketOrderManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()
        assert bus.subscriber_count >= 5  # 5 channels

        await mgr.unwire_events()
        # Subscriptions should be removed

    @pytest.mark.asyncio
    async def test_events_not_processed_after_unwire(self, bus, mock_exec):
        mgr = BracketOrderManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        bracket = await submit_default_market_bracket(mgr)
        await mgr.unwire_events()

        # This fill should not be processed since we unwired
        await bus.publish("execution.order.filled", {
            "order_id": bracket.entry_order_id,
            "fill_price": "150.00",
        })
        assert bracket.state == BracketState.ENTRY_PLACED


# ── Multiple Brackets ─────────────────────────────────────────────────


class TestMultipleBrackets:
    @pytest.mark.asyncio
    async def test_multiple_brackets_same_symbol(self, wired_manager, bus, mock_exec):
        """Multiple brackets for the same symbol are managed independently."""
        b1 = await submit_default_market_bracket(wired_manager)
        b2 = await submit_default_market_bracket(wired_manager)

        # Fill both entries
        await fill_entry(bus, b1)
        await fill_entry(bus, b2)
        assert b1.state == BracketState.MONITORING
        assert b2.state == BracketState.MONITORING

        # Stop one
        await fill_stop_loss(bus, b1)
        assert b1.state == BracketState.STOPPED_OUT
        assert b2.state == BracketState.MONITORING

    @pytest.mark.asyncio
    async def test_multiple_brackets_different_symbols(self, wired_manager, bus, mock_exec):
        """Brackets for different symbols track independently."""
        b1 = await wired_manager.submit_bracket_order(
            symbol="AAPL", quantity=10, entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"), take_profit_price=Decimal("160"),
        )
        b2 = await wired_manager.submit_bracket_order(
            symbol="MSFT", quantity=5, entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("300"), take_profit_price=Decimal("350"),
        )

        await fill_entry(bus, b1)
        await fill_entry(bus, b2)

        # Quote only for AAPL
        await send_quote(bus, "AAPL", 160.0)
        assert b1.state == BracketState.TAKE_PROFIT_TRIGGERED
        assert b2.state == BracketState.MONITORING


# ── QuoteTick Object Tests ───────────────────────────────────────────


class TestQuoteTickHandling:
    @pytest.mark.asyncio
    async def test_quote_tick_object(self, wired_manager, bus, mock_exec):
        """Handle QuoteTick objects (not just dicts)."""
        from datetime import datetime, timezone

        bracket = await submit_default_market_bracket(wired_manager)
        await fill_entry(bus, bracket)

        quote = QuoteTick(
            symbol="AAPL",
            bid_price=160.0,
            ask_price=160.05,
            bid_size=100,
            ask_size=100,
            timestamp=datetime.now(timezone.utc),
        )
        await bus.publish("quote", quote)
        assert bracket.state == BracketState.TAKE_PROFIT_TRIGGERED
