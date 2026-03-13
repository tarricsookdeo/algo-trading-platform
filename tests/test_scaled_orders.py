"""Comprehensive tests for the scaled order manager."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.core.events import EventBus
from trading_platform.orders.scaled import (
    SCALED_ORDER_TERMINAL_STATES,
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
    exec_adapter = AsyncMock()
    exec_adapter.submit_order = AsyncMock(return_value=None)
    exec_adapter.cancel_order = AsyncMock(return_value=None)
    del exec_adapter.cancel_and_replace
    return exec_adapter


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
    await bus.publish("quote", {"symbol": symbol, "bid_price": str(bid_price)})


async def fill_order(bus, order_id, fill_price=None):
    event = {"order_id": order_id}
    if fill_price is not None:
        event["fill_price"] = str(fill_price)
    await bus.publish("execution.order.filled", event)


# ── Tests: Scaled Exit Creation ───────────────────────────────────────


class TestScaledExitCreation:

    @pytest.mark.asyncio
    async def test_create_two_tranche_exit(self, wired_manager, mock_exec):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        assert order.symbol == "AAPL"
        assert order.total_quantity == Decimal("100")
        assert order.remaining_quantity == Decimal("100")
        assert len(order.tranches) == 2
        assert order.tranches[0].price == Decimal("160")
        assert order.tranches[0].quantity == Decimal("50")
        assert order.tranches[1].price == Decimal("170")
        assert order.tranches[1].quantity == Decimal("50")
        assert order.state == ScaledOrderState.ACTIVE
        mock_exec.submit_order.assert_called_once()  # stop order

    @pytest.mark.asyncio
    async def test_create_three_tranche_exit(self, wired_manager):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.33")),
                (Decimal("170"), Decimal("0.33")),
                (Decimal("180"), Decimal("0.34")),
            ],
            stop_loss_price=Decimal("140"),
        )
        assert len(order.tranches) == 3
        total_qty = sum(t.quantity for t in order.tranches)
        assert total_qty == Decimal("100")

    @pytest.mark.asyncio
    async def test_percentages_must_sum_to_one(self, wired_manager):
        with pytest.raises(ValueError, match="sum to 1.0"):
            await wired_manager.create_scaled_exit(
                symbol="AAPL",
                total_quantity=Decimal("100"),
                take_profit_levels=[
                    (Decimal("160"), Decimal("0.3")),
                    (Decimal("170"), Decimal("0.3")),
                ],
                stop_loss_price=Decimal("140"),
            )

    @pytest.mark.asyncio
    async def test_empty_levels_raises(self, wired_manager):
        with pytest.raises(ValueError, match="at least one"):
            await wired_manager.create_scaled_exit(
                symbol="AAPL",
                total_quantity=Decimal("100"),
                take_profit_levels=[],
                stop_loss_price=Decimal("140"),
            )

    @pytest.mark.asyncio
    async def test_zero_quantity_raises(self, wired_manager):
        with pytest.raises(ValueError, match="total_quantity must be positive"):
            await wired_manager.create_scaled_exit(
                symbol="AAPL",
                total_quantity=Decimal("0"),
                take_profit_levels=[(Decimal("160"), Decimal("1"))],
                stop_loss_price=Decimal("140"),
            )

    @pytest.mark.asyncio
    async def test_no_exec_adapter_raises(self, bus):
        mgr = ScaledOrderManager(event_bus=bus, exec_adapter=None)
        with pytest.raises(RuntimeError, match="No execution adapter"):
            await mgr.create_scaled_exit(
                symbol="AAPL",
                total_quantity=Decimal("100"),
                take_profit_levels=[(Decimal("160"), Decimal("1"))],
                stop_loss_price=Decimal("140"),
            )


# ── Tests: Scaled Exit Tranche Fills ─────────────────────────────────


class TestScaledExitTranches:

    @pytest.mark.asyncio
    async def test_first_tranche_triggers_on_bid(self, wired_manager, bus, mock_exec):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        # Bid reaches first tranche level
        await send_quote(bus, "AAPL", "160")
        assert order.tranches[0].filled is True
        assert order.remaining_quantity == Decimal("50")
        # Market sell + stop re-placement = 2 more calls
        assert mock_exec.submit_order.call_count >= 2

    @pytest.mark.asyncio
    async def test_all_tranches_complete(self, wired_manager, bus, mock_exec):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        await send_quote(bus, "AAPL", "160")
        await send_quote(bus, "AAPL", "170")
        assert order.tranches[0].filled is True
        assert order.tranches[1].filled is True
        assert order.remaining_quantity == Decimal("0")
        assert order.state == ScaledOrderState.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_loss_fills_remaining(self, wired_manager, bus, mock_exec):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        # Stop fills before any tranche
        await fill_order(bus, order.stop_order_id, "139.50")
        assert order.state == ScaledOrderState.COMPLETED

    @pytest.mark.asyncio
    async def test_partial_then_stop(self, wired_manager, bus, mock_exec):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        # First tranche fills
        await send_quote(bus, "AAPL", "160")
        assert order.remaining_quantity == Decimal("50")

        # Stop fills the rest
        await fill_order(bus, order.stop_order_id, "139.50")
        assert order.state == ScaledOrderState.COMPLETED

    @pytest.mark.asyncio
    async def test_tranche_sell_failure_reverts(self, wired_manager, bus, mock_exec):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        # Make the sell fail after the stop is placed
        mock_exec.submit_order = AsyncMock(side_effect=Exception("sell failed"))

        await send_quote(bus, "AAPL", "160")
        # Tranche should be reverted
        assert order.tranches[0].filled is False
        assert order.remaining_quantity == Decimal("100")

    @pytest.mark.asyncio
    async def test_completion_event_emitted(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(ScaledOrderChannel.SCALED_EXIT_COMPLETED, _collect)

        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_price=Decimal("140"),
        )
        await send_quote(bus, "AAPL", "160")
        assert len(events) == 1
        assert events[0]["scaled_id"] == order.scaled_id

    @pytest.mark.asyncio
    async def test_different_symbol_ignored(self, wired_manager, bus, mock_exec):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_price=Decimal("140"),
        )
        await send_quote(bus, "GOOG", "300")
        assert order.tranches[0].filled is False


# ── Tests: Scaled Entry ───────────────────────────────────────────────


class TestScaledEntry:

    @pytest.mark.asyncio
    async def test_create_scaled_entry(self, wired_manager, mock_exec):
        entry = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            entry_levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        assert entry.symbol == "AAPL"
        assert entry.total_quantity == Decimal("100")
        assert entry.filled_quantity == Decimal("0")
        assert len(entry.tranches) == 2
        assert entry.state == ScaledOrderState.ACTIVE
        # 2 limit buy orders placed
        assert mock_exec.submit_order.call_count == 2

    @pytest.mark.asyncio
    async def test_entry_tranche_fill_places_stop(self, wired_manager, bus, mock_exec):
        entry = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            entry_levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        # First tranche fills
        await fill_order(bus, entry.tranches[0].order_id, "145")
        assert entry.filled_quantity == Decimal("50")
        assert entry.tranches[0].filled is True
        # Stop should be placed for filled quantity
        assert entry.stop_order_id is not None

    @pytest.mark.asyncio
    async def test_all_entry_tranches_fill(self, wired_manager, bus, mock_exec):
        entry = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            entry_levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        await fill_order(bus, entry.tranches[0].order_id, "145")
        await fill_order(bus, entry.tranches[1].order_id, "140")
        assert entry.filled_quantity == Decimal("100")
        assert entry.state == ScaledOrderState.COMPLETED

    @pytest.mark.asyncio
    async def test_entry_stop_loss_fills(self, wired_manager, bus, mock_exec):
        entry = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            entry_levels=[
                (Decimal("145"), Decimal("0.5")),
                (Decimal("140"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("135"),
        )
        # Fill first tranche to get a stop order
        await fill_order(bus, entry.tranches[0].order_id, "145")
        stop_id = entry.stop_order_id

        # Stop fills
        await fill_order(bus, stop_id, "134")
        assert entry.state == ScaledOrderState.COMPLETED

    @pytest.mark.asyncio
    async def test_entry_percentages_must_sum_to_one(self, wired_manager):
        with pytest.raises(ValueError, match="sum to 1.0"):
            await wired_manager.create_scaled_entry(
                symbol="AAPL",
                total_quantity=Decimal("100"),
                entry_levels=[(Decimal("145"), Decimal("0.3"))],
                stop_loss_price=Decimal("135"),
            )

    @pytest.mark.asyncio
    async def test_entry_empty_levels_raises(self, wired_manager):
        with pytest.raises(ValueError, match="at least one"):
            await wired_manager.create_scaled_entry(
                symbol="AAPL",
                total_quantity=Decimal("100"),
                entry_levels=[],
                stop_loss_price=Decimal("135"),
            )

    @pytest.mark.asyncio
    async def test_entry_zero_quantity_raises(self, wired_manager):
        with pytest.raises(ValueError, match="total_quantity must be positive"):
            await wired_manager.create_scaled_entry(
                symbol="AAPL",
                total_quantity=Decimal("0"),
                entry_levels=[(Decimal("145"), Decimal("1"))],
                stop_loss_price=Decimal("135"),
            )

    @pytest.mark.asyncio
    async def test_entry_no_exec_raises(self, bus):
        mgr = ScaledOrderManager(event_bus=bus, exec_adapter=None)
        with pytest.raises(RuntimeError, match="No execution adapter"):
            await mgr.create_scaled_entry(
                symbol="AAPL",
                total_quantity=Decimal("100"),
                entry_levels=[(Decimal("145"), Decimal("1"))],
                stop_loss_price=Decimal("135"),
            )

    @pytest.mark.asyncio
    async def test_entry_tranche_filled_event(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(
            ScaledOrderChannel.SCALED_ENTRY_TRANCHE_FILLED,
            _collect,
        )
        entry = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            entry_levels=[(Decimal("145"), Decimal("1"))],
            stop_loss_price=Decimal("135"),
        )
        await fill_order(bus, entry.tranches[0].order_id, "145")
        assert len(events) == 1
        assert events[0]["scaled_id"] == entry.scaled_id


# ── Tests: Query ──────────────────────────────────────────────────────


class TestScaledOrderQuery:

    @pytest.mark.asyncio
    async def test_get_scaled_exit(self, wired_manager):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_price=Decimal("140"),
        )
        found = wired_manager.get_scaled_exit(order.scaled_id)
        assert found is order

    @pytest.mark.asyncio
    async def test_get_scaled_entry(self, wired_manager):
        entry = await wired_manager.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            entry_levels=[(Decimal("145"), Decimal("1"))],
            stop_loss_price=Decimal("135"),
        )
        found = wired_manager.get_scaled_entry(entry.scaled_id)
        assert found is entry

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, wired_manager):
        assert wired_manager.get_scaled_exit("nope") is None
        assert wired_manager.get_scaled_entry("nope") is None


# ── Tests: Stop Adjustment ────────────────────────────────────────────


class TestScaledStopAdjustment:

    @pytest.mark.asyncio
    async def test_exit_stop_adjusted_after_tranche(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(ScaledOrderChannel.SCALED_STOP_ADJUSTED, _collect)

        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        await send_quote(bus, "AAPL", "160")
        # Stop adjustment event should fire
        assert len(events) >= 1
        assert events[-1]["new_quantity"] == "50"

    @pytest.mark.asyncio
    async def test_exit_stop_cancel_and_replace(self, bus):
        mock_exec = AsyncMock()
        mock_exec.submit_order = AsyncMock(return_value=None)
        mock_exec.cancel_order = AsyncMock(return_value=None)

        replace_result = AsyncMock()
        replace_result.order_id = "new-stop-123"
        mock_exec.cancel_and_replace = AsyncMock(return_value=replace_result)

        mgr = ScaledOrderManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        order = await mgr.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        await send_quote(bus, "AAPL", "160")
        mock_exec.cancel_and_replace.assert_called_once()
        assert order.stop_order_id == "new-stop-123"

        await mgr.unwire_events()


# ── Tests: Models & Enums ────────────────────────────────────────────


class TestScaledOrderModels:

    def test_terminal_states(self):
        assert ScaledOrderState.COMPLETED in SCALED_ORDER_TERMINAL_STATES
        assert ScaledOrderState.CANCELED in SCALED_ORDER_TERMINAL_STATES
        assert ScaledOrderState.ERROR in SCALED_ORDER_TERMINAL_STATES
        assert ScaledOrderState.ACTIVE not in SCALED_ORDER_TERMINAL_STATES

    def test_tranche_dataclass(self):
        t = Tranche(price=Decimal("160"), quantity=Decimal("50"))
        assert t.filled is False
        assert t.order_id is None

    def test_scaled_exit_remaining_quantity(self):
        order = ScaledExitOrder(
            scaled_id="test-1",
            symbol="AAPL",
            total_quantity=Decimal("100"),
            tranches=[],
            stop_loss_price=Decimal("140"),
        )
        assert order.remaining_quantity == Decimal("100")

    def test_scaled_entry_defaults(self):
        entry = ScaledEntryOrder(
            scaled_id="test-1",
            symbol="AAPL",
            total_quantity=Decimal("100"),
            tranches=[],
            stop_loss_price=Decimal("135"),
        )
        assert entry.filled_quantity == Decimal("0")
        assert entry.state == ScaledOrderState.PENDING

    def test_channel_values(self):
        assert ScaledOrderChannel.SCALED_EXIT_PLACED == "scaled.exit.placed"
        assert ScaledOrderChannel.SCALED_EXIT_COMPLETED == "scaled.exit.completed"
        assert ScaledOrderChannel.SCALED_ENTRY_PLACED == "scaled.entry.placed"


# ── Tests: Wiring ────────────────────────────────────────────────────


class TestScaledOrderWiring:

    @pytest.mark.asyncio
    async def test_wire_and_unwire(self, manager, bus):
        await manager.wire_events()
        assert bus.subscriber_count > 0
        await manager.unwire_events()

    @pytest.mark.asyncio
    async def test_state_change_event(self, wired_manager, bus):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(ScaledOrderChannel.SCALED_STATE_CHANGE, _collect)

        await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_price=Decimal("140"),
        )
        assert any(e["to_state"] == str(ScaledOrderState.ACTIVE) for e in events)


# ── Tests: Error Handling ────────────────────────────────────────────


class TestScaledOrderErrors:

    @pytest.mark.asyncio
    async def test_exit_stop_placement_failure(self, bus, mock_exec):
        mock_exec.submit_order = AsyncMock(side_effect=Exception("network error"))
        mgr = ScaledOrderManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        order = await mgr.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[(Decimal("160"), Decimal("1"))],
            stop_loss_price=Decimal("140"),
        )
        assert order.state == ScaledOrderState.ERROR

        await mgr.unwire_events()

    @pytest.mark.asyncio
    async def test_entry_all_orders_fail(self, bus, mock_exec):
        mock_exec.submit_order = AsyncMock(side_effect=Exception("all fail"))
        mgr = ScaledOrderManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        entry = await mgr.create_scaled_entry(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            entry_levels=[(Decimal("145"), Decimal("1"))],
            stop_loss_price=Decimal("135"),
        )
        assert entry.state == ScaledOrderState.ERROR

        await mgr.unwire_events()


# ── Tests: Rounding Fix ──────────────────────────────────────────────


class TestScaledOrderRounding:

    @pytest.mark.asyncio
    async def test_rounding_adjustment(self, wired_manager):
        # 100 shares split 33/33/34 — should sum to 100
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("100"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.333")),
                (Decimal("170"), Decimal("0.333")),
                (Decimal("180"), Decimal("0.334")),
            ],
            stop_loss_price=Decimal("140"),
        )
        total = sum(t.quantity for t in order.tranches)
        assert total == Decimal("100")

    @pytest.mark.asyncio
    async def test_odd_quantity_no_rounding_error(self, wired_manager):
        order = await wired_manager.create_scaled_exit(
            symbol="AAPL",
            total_quantity=Decimal("7"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
            stop_loss_price=Decimal("140"),
        )
        total = sum(t.quantity for t in order.tranches)
        assert total == Decimal("7")
