"""Comprehensive tests for the scaled order module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.orders.scaled import (
    SCALED_TERMINAL_STATES,
    ScaledEntryOrder,
    ScaledExitOrder,
    ScaledOrderChannel,
    ScaledOrderManager,
    ScaledOrderState,
    Tranche,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_exec():
    adapter = AsyncMock()
    adapter.submit_order = AsyncMock(return_value=None)
    adapter.cancel_order = AsyncMock(return_value=None)
    return adapter


@pytest.fixture
def manager(bus, mock_exec):
    return ScaledOrderManager(event_bus=bus, exec_adapter=mock_exec)


@pytest.fixture
async def wired_manager(manager, bus):
    await manager.wire_events()
    yield manager
    await manager.unwire_events()


# ── Helpers ───────────────────────────────────────────────────────────


async def send_quote(bus, symbol, bid_price):
    await bus.publish("quote", {
        "symbol": symbol,
        "bid_price": bid_price,
        "ask_price": bid_price + 0.01,
        "bid_size": 100,
        "ask_size": 100,
    })


async def fill_order(bus, order_id, fill_price):
    await bus.publish("execution.order.filled", {
        "order_id": order_id,
        "fill_price": str(fill_price),
    })


# ── Model Tests ──────────────────────────────────────────────────────


class TestScaledModels:
    def test_tranche_model(self):
        t = Tranche(price=Decimal("160"), quantity=Decimal("5"), quantity_percent=Decimal("0.5"))
        assert t.price == Decimal("160")
        assert t.filled is False
        assert t.order_id is None

    def test_scaled_exit_model(self):
        scaled = ScaledExitOrder(
            scaled_order_id="se-1",
            symbol="AAPL",
            total_quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            tranches=[
                Tranche(price=Decimal("155"), quantity=Decimal("5"), quantity_percent=Decimal("0.5")),
                Tranche(price=Decimal("160"), quantity=Decimal("5"), quantity_percent=Decimal("0.5")),
            ],
        )
        assert scaled.state == ScaledOrderState.PENDING
        assert len(scaled.tranches) == 2

    def test_scaled_entry_model(self):
        scaled = ScaledEntryOrder(
            scaled_order_id="se-2",
            symbol="AAPL",
            total_quantity=Decimal("100"),
            tranches=[
                Tranche(price=Decimal("145"), quantity=Decimal("50"), quantity_percent=Decimal("0.5")),
                Tranche(price=Decimal("140"), quantity=Decimal("50"), quantity_percent=Decimal("0.5")),
            ],
        )
        assert scaled.filled_quantity == Decimal("0")

    def test_terminal_states(self):
        assert ScaledOrderState.COMPLETED in SCALED_TERMINAL_STATES
        assert ScaledOrderState.CANCELED in SCALED_TERMINAL_STATES
        assert ScaledOrderState.ERROR in SCALED_TERMINAL_STATES
        assert ScaledOrderState.ACTIVE not in SCALED_TERMINAL_STATES


# ── Validation ───────────────────────────────────────────────────────


class TestScaledOrderValidation:
    @pytest.mark.asyncio
    async def test_no_exec_adapter_raises(self, bus):
        mgr = ScaledOrderManager(event_bus=bus, exec_adapter=None)
        with pytest.raises(RuntimeError, match="No execution adapter"):
            await mgr.create_scaled_exit(
                "AAPL", Decimal("10"),
                [(Decimal("160"), Decimal("1"))],
            )

    @pytest.mark.asyncio
    async def test_no_levels_raises(self, manager):
        with pytest.raises(ValueError, match="At least one exit level"):
            await manager.create_scaled_exit("AAPL", Decimal("10"), [])

    @pytest.mark.asyncio
    async def test_zero_quantity_raises(self, manager):
        with pytest.raises(ValueError, match="total_quantity must be positive"):
            await manager.create_scaled_exit(
                "AAPL", Decimal("0"),
                [(Decimal("160"), Decimal("1"))],
            )

    @pytest.mark.asyncio
    async def test_percentages_not_summing_to_one_raises(self, manager):
        with pytest.raises(ValueError, match="percentages must sum to 1.0"):
            await manager.create_scaled_exit(
                "AAPL", Decimal("10"),
                [(Decimal("155"), Decimal("0.3")), (Decimal("160"), Decimal("0.3"))],
            )

    @pytest.mark.asyncio
    async def test_entry_no_exec_raises(self, bus):
        mgr = ScaledOrderManager(event_bus=bus, exec_adapter=None)
        with pytest.raises(RuntimeError, match="No execution adapter"):
            await mgr.create_scaled_entry(
                "AAPL", Decimal("10"),
                [(Decimal("145"), Decimal("1"))],
            )

    @pytest.mark.asyncio
    async def test_entry_no_levels_raises(self, manager):
        with pytest.raises(ValueError, match="At least one entry level"):
            await manager.create_scaled_entry("AAPL", Decimal("10"), [])

    @pytest.mark.asyncio
    async def test_entry_zero_quantity_raises(self, manager):
        with pytest.raises(ValueError, match="total_quantity must be positive"):
            await manager.create_scaled_entry(
                "AAPL", Decimal("0"),
                [(Decimal("145"), Decimal("1"))],
            )


# ── Scaled Exit Creation ─────────────────────────────────────────────


class TestScaledExitCreation:
    @pytest.mark.asyncio
    async def test_create_two_level_exit(self, manager):
        scaled = await manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        assert scaled.state == ScaledOrderState.ACTIVE
        assert len(scaled.tranches) == 2
        assert scaled.tranches[0].quantity == Decimal("50")
        assert scaled.tranches[1].quantity == Decimal("50")
        assert scaled.remaining_quantity == Decimal("100")

    @pytest.mark.asyncio
    async def test_create_three_level_exit_rounding(self, manager):
        scaled = await manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.33")),
                (Decimal("160"), Decimal("0.33")),
                (Decimal("165"), Decimal("0.34")),
            ],
        )
        total = sum(t.quantity for t in scaled.tranches)
        assert total == Decimal("100")

    @pytest.mark.asyncio
    async def test_exit_created_event_emitted(self, manager, bus):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(ScaledOrderChannel.SCALED_EXIT_CREATED, _collect)

        scaled = await manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        assert len(events) == 1
        assert events[0]["scaled_order_id"] == scaled.scaled_order_id

    @pytest.mark.asyncio
    async def test_get_scaled_exit(self, manager):
        scaled = await manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        assert manager.get_scaled_exit(scaled.scaled_order_id) is scaled
        assert manager.get_scaled_exit("nonexistent") is None

    @pytest.mark.asyncio
    async def test_create_with_stop_loss_info(self, manager):
        scaled = await manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_order_id="stop-123",
            stop_loss_price=Decimal("140"),
        )
        assert scaled.stop_loss_order_id == "stop-123"
        assert scaled.stop_loss_price == Decimal("140")


# ── Scaled Exit Tranche Execution ────────────────────────────────────


class TestScaledExitExecution:
    @pytest.mark.asyncio
    async def test_tranche_triggered_on_price_reach(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        mock_exec.reset_mock()

        # Price reaches first tranche level
        await send_quote(bus, "AAPL", 155)
        # Should have submitted a market sell
        mock_exec.submit_order.assert_called_once()
        order = mock_exec.submit_order.call_args[0][0]
        assert order.side == OrderSide.SELL
        assert order.order_type == OrderType.MARKET
        assert order.quantity == Decimal("50")

    @pytest.mark.asyncio
    async def test_both_tranches_triggered_at_high_price(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        mock_exec.reset_mock()

        # Price above both levels
        await send_quote(bus, "AAPL", 165)
        assert mock_exec.submit_order.call_count == 2

    @pytest.mark.asyncio
    async def test_tranche_fill_updates_remaining_quantity(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
            stop_loss_order_id="stop-123",
            stop_loss_price=Decimal("140"),
        )
        # Trigger first tranche
        await send_quote(bus, "AAPL", 155)
        sell_order_id = scaled.tranches[0].order_id

        # Simulate fill
        await fill_order(bus, sell_order_id, 155.25)
        assert scaled.tranches[0].filled is True
        assert scaled.remaining_quantity == Decimal("50")

    @pytest.mark.asyncio
    async def test_tranche_fill_adjusts_stop_loss(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
            stop_loss_order_id="stop-123",
            stop_loss_price=Decimal("140"),
        )
        mock_exec.reset_mock()

        # Trigger and fill first tranche
        await send_quote(bus, "AAPL", 155)
        sell_order_id = scaled.tranches[0].order_id
        await fill_order(bus, sell_order_id, 155.25)

        # Should have cancelled old stop and placed new one with reduced quantity
        mock_exec.cancel_order.assert_called_with("stop-123")
        # New stop order submitted with remaining quantity
        new_stop_call = mock_exec.submit_order.call_args[0][0]
        assert new_stop_call.quantity == Decimal("50")
        assert new_stop_call.stop_price == 140.0

    @pytest.mark.asyncio
    async def test_all_tranches_filled_completes_order(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
            stop_loss_order_id="stop-123",
            stop_loss_price=Decimal("140"),
        )

        # Trigger and fill both tranches
        await send_quote(bus, "AAPL", 155)
        await fill_order(bus, scaled.tranches[0].order_id, 155.25)

        await send_quote(bus, "AAPL", 160)
        await fill_order(bus, scaled.tranches[1].order_id, 160.50)

        assert scaled.state == ScaledOrderState.COMPLETED
        assert scaled.remaining_quantity == Decimal("0")
        assert scaled.completed_at is not None

    @pytest.mark.asyncio
    async def test_all_tranches_filled_cancels_stop(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_order_id="stop-123",
            stop_loss_price=Decimal("140"),
        )
        mock_exec.reset_mock()

        # Trigger and fill the single tranche
        await send_quote(bus, "AAPL", 160)
        await fill_order(bus, scaled.tranches[0].order_id, 160.50)

        # Should cancel the stop since all tranches filled
        mock_exec.cancel_order.assert_called_with("stop-123")
        assert scaled.state == ScaledOrderState.COMPLETED

    @pytest.mark.asyncio
    async def test_completed_event_emitted(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(ScaledOrderChannel.SCALED_EXIT_COMPLETED, _collect)

        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        await send_quote(bus, "AAPL", 160)
        await fill_order(bus, scaled.tranches[0].order_id, 160)

        assert len(events) == 1
        assert events[0]["scaled_order_id"] == scaled.scaled_order_id

    @pytest.mark.asyncio
    async def test_tranche_filled_event_emitted(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(ScaledOrderChannel.SCALED_EXIT_TRANCHE_FILLED, _collect)

        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await send_quote(bus, "AAPL", 155)
        await fill_order(bus, scaled.tranches[0].order_id, 155)

        assert len(events) == 1
        assert events[0]["tranche_index"] == 0
        assert events[0]["remaining_quantity"] == "50"

    @pytest.mark.asyncio
    async def test_ignores_other_symbols(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        mock_exec.reset_mock()

        await send_quote(bus, "GOOG", 3000)
        mock_exec.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_price_below_tranche_does_not_trigger(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        mock_exec.reset_mock()

        await send_quote(bus, "AAPL", 159.99)
        mock_exec.submit_order.assert_not_called()


# ── Scaled Entry Creation ────────────────────────────────────────────


class TestScaledEntryCreation:
    @pytest.mark.asyncio
    async def test_create_entry_places_limit_buys(self, manager, mock_exec):
        scaled = await manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        assert scaled.state == ScaledOrderState.ACTIVE
        # Two limit buy orders placed
        assert mock_exec.submit_order.call_count == 2
        orders = [call[0][0] for call in mock_exec.submit_order.call_args_list]
        assert all(o.side == OrderSide.BUY for o in orders)
        assert all(o.order_type == OrderType.LIMIT for o in orders)
        assert orders[0].limit_price == 145.0
        assert orders[1].limit_price == 140.0

    @pytest.mark.asyncio
    async def test_entry_created_event_emitted(self, manager, bus, mock_exec):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(ScaledOrderChannel.SCALED_ENTRY_CREATED, _collect)

        scaled = await manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("145"), Decimal("1"))],
        )
        assert len(events) == 1
        assert events[0]["scaled_order_id"] == scaled.scaled_order_id

    @pytest.mark.asyncio
    async def test_get_scaled_entry(self, manager, mock_exec):
        scaled = await manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("145"), Decimal("1"))],
        )
        assert manager.get_scaled_entry(scaled.scaled_order_id) is scaled
        assert manager.get_scaled_entry("nonexistent") is None

    @pytest.mark.asyncio
    async def test_entry_placement_failure(self, manager, mock_exec):
        mock_exec.submit_order.side_effect = Exception("Network error")
        scaled = await manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("145"), Decimal("1"))],
        )
        assert scaled.state == ScaledOrderState.ERROR


# ── Scaled Entry Fills ───────────────────────────────────────────────


class TestScaledEntryFills:
    @pytest.mark.asyncio
    async def test_entry_fill_places_stop_loss(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        mock_exec.reset_mock()

        # Fill first tranche
        await fill_order(bus, scaled.tranches[0].order_id, 145)
        assert scaled.tranches[0].filled is True
        assert scaled.filled_quantity == Decimal("50")

        # Stop placed for 50 shares
        stop_call = mock_exec.submit_order.call_args[0][0]
        assert stop_call.side == OrderSide.SELL
        assert stop_call.order_type == OrderType.STOP
        assert stop_call.quantity == Decimal("50")
        assert stop_call.stop_price == 135.0

    @pytest.mark.asyncio
    async def test_second_fill_adjusts_stop(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        mock_exec.reset_mock()

        # Fill first tranche
        await fill_order(bus, scaled.tranches[0].order_id, 145)
        first_stop_id = scaled.stop_loss_order_id
        mock_exec.reset_mock()

        # Fill second tranche
        await fill_order(bus, scaled.tranches[1].order_id, 140)
        assert scaled.filled_quantity == Decimal("100")

        # Old stop cancelled, new one placed for full quantity
        mock_exec.cancel_order.assert_called_once_with(first_stop_id)
        new_stop = mock_exec.submit_order.call_args[0][0]
        assert new_stop.quantity == Decimal("100")

    @pytest.mark.asyncio
    async def test_all_entries_filled_marks_completed(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("145"), Decimal("1"))],
            stop_loss_price=Decimal("135"),
        )
        await fill_order(bus, scaled.tranches[0].order_id, 145)
        assert scaled.state == ScaledOrderState.COMPLETED

    @pytest.mark.asyncio
    async def test_entry_tranche_filled_event(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(ScaledOrderChannel.SCALED_ENTRY_TRANCHE_FILLED, _collect)

        scaled = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("145"), Decimal("1"))],
        )
        await fill_order(bus, scaled.tranches[0].order_id, 145)

        assert len(events) == 1
        assert events[0]["tranche_index"] == 0

    @pytest.mark.asyncio
    async def test_entry_without_stop_loss(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("145"), Decimal("1"))],
            stop_loss_price=None,
        )
        mock_exec.reset_mock()

        # Fill — no stop should be placed
        await fill_order(bus, scaled.tranches[0].order_id, 145)
        mock_exec.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_entry_stop_fill_cancels_unfilled_tranches(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )

        # Fill first tranche
        await fill_order(bus, scaled.tranches[0].order_id, 145)
        stop_order_id = scaled.stop_loss_order_id
        mock_exec.reset_mock()

        # Stop gets filled
        await fill_order(bus, stop_order_id, 135)
        assert scaled.state == ScaledOrderState.COMPLETED

        # Unfilled second tranche should have been cancelled
        mock_exec.cancel_order.assert_called_once_with(scaled.tranches[1].order_id)


# ── Cancellation ─────────────────────────────────────────────────────


class TestScaledOrderCancel:
    @pytest.mark.asyncio
    async def test_cancel_exit_order(self, manager, bus):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(ScaledOrderChannel.SCALED_ORDER_CANCELED, _collect)

        scaled = await manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        result = await manager.cancel_scaled_order(scaled.scaled_order_id)
        assert result is True
        assert scaled.state == ScaledOrderState.CANCELED
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_cancel_entry_order(self, manager, mock_exec, bus):
        scaled = await manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        mock_exec.reset_mock()

        result = await manager.cancel_scaled_order(scaled.scaled_order_id)
        assert result is True
        assert scaled.state == ScaledOrderState.CANCELED
        # Both unfilled tranche orders should be cancelled
        assert mock_exec.cancel_order.call_count == 2

    @pytest.mark.asyncio
    async def test_cancel_entry_with_stop(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("145"), Decimal("1"))],
            stop_loss_price=Decimal("135"),
        )
        # Fill entry to get stop placed
        await fill_order(bus, scaled.tranches[0].order_id, 145)
        mock_exec.reset_mock()

        # Entry is now completed, can't cancel
        result = await wired_manager.cancel_scaled_order(scaled.scaled_order_id)
        assert result is False  # Already completed

    @pytest.mark.asyncio
    async def test_cancel_completed_returns_false(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        await send_quote(bus, "AAPL", 160)
        await fill_order(bus, scaled.tranches[0].order_id, 160)
        assert scaled.state == ScaledOrderState.COMPLETED

        result = await wired_manager.cancel_scaled_order(scaled.scaled_order_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, manager):
        result = await manager.cancel_scaled_order("nonexistent")
        assert result is False


# ── Edge Cases ───────────────────────────────────────────────────────


class TestScaledOrderEdgeCases:
    @pytest.mark.asyncio
    async def test_fill_event_without_order_id_ignored(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        await bus.publish("execution.order.filled", {"fill_price": "160"})
        assert scaled.state == ScaledOrderState.ACTIVE

    @pytest.mark.asyncio
    async def test_non_dict_event_ignored(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        await bus.publish("quote", "not-a-valid-event")
        assert scaled.remaining_quantity == Decimal("100")

    @pytest.mark.asyncio
    async def test_fill_with_avg_price_fallback(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
        )
        await send_quote(bus, "AAPL", 160)
        # Use avg_price instead of fill_price
        await bus.publish("execution.order.filled", {
            "order_id": scaled.tranches[0].order_id,
            "avg_price": "160.50",
        })
        assert scaled.tranches[0].fill_price == Decimal("160.50")

    @pytest.mark.asyncio
    async def test_no_double_trigger(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("155"), Decimal("1"))],
        )
        mock_exec.reset_mock()

        # First quote triggers
        await send_quote(bus, "AAPL", 155)
        assert mock_exec.submit_order.call_count == 1
        mock_exec.reset_mock()

        # Fill the tranche
        await fill_order(bus, scaled.tranches[0].order_id, 155)

        # Second quote at same level — should NOT re-trigger
        await send_quote(bus, "AAPL", 155)
        mock_exec.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_exit_stop_cancel_failure_is_graceful(self, wired_manager, bus, mock_exec):
        scaled = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_order_id="stop-123",
            stop_loss_price=Decimal("140"),
        )
        mock_exec.cancel_order.side_effect = Exception("Cancel failed")

        # Trigger and fill — stop cancel should fail gracefully
        await send_quote(bus, "AAPL", 160)
        await fill_order(bus, scaled.tranches[0].order_id, 160)
        # Order still completes despite stop cancel failure
        assert scaled.state == ScaledOrderState.COMPLETED
