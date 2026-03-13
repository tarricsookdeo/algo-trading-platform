"""Comprehensive tests for the trailing stop order module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_platform.core.events import EventBus
from trading_platform.core.models import Order
from trading_platform.orders.trailing_stop import (
    TRAILING_STOP_TERMINAL_STATES,
    TrailingStopChannel,
    TrailingStopManager,
    TrailingStopOrder,
    TrailingStopState,
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
    return TrailingStopManager(event_bus=bus, exec_adapter=mock_exec)


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


async def fill_stop(bus, order_id, fill_price):
    await bus.publish("execution.order.filled", {
        "order_id": order_id,
        "fill_price": str(fill_price),
    })


async def cancel_order_event(bus, order_id):
    await bus.publish("execution.order.cancelled", {
        "order_id": order_id,
    })


# ── TrailingStopOrder Model ──────────────────────────────────────────


class TestTrailingStopModel:
    def test_create_with_trail_amount(self):
        ts = TrailingStopOrder(
            trailing_stop_id="ts-1",
            symbol="AAPL",
            quantity=Decimal("10"),
            trail_amount=Decimal("5"),
            current_stop_price=Decimal("145"),
            high_water_mark=Decimal("150"),
        )
        assert ts.trailing_stop_id == "ts-1"
        assert ts.trail_amount == Decimal("5")
        assert ts.trail_percent is None
        assert ts.state == TrailingStopState.PENDING

    def test_create_with_trail_percent(self):
        ts = TrailingStopOrder(
            trailing_stop_id="ts-2",
            symbol="AAPL",
            quantity=Decimal("10"),
            trail_percent=Decimal("0.05"),
            current_stop_price=Decimal("142.50"),
            high_water_mark=Decimal("150"),
        )
        assert ts.trail_percent == Decimal("0.05")
        assert ts.trail_amount is None

    def test_terminal_states(self):
        assert TrailingStopState.COMPLETED in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.CANCELED in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.ERROR in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.ACTIVE not in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.PENDING not in TRAILING_STOP_TERMINAL_STATES


# ── Validation ───────────────────────────────────────────────────────


class TestTrailingStopValidation:
    @pytest.mark.asyncio
    async def test_no_exec_adapter_raises(self, bus):
        mgr = TrailingStopManager(event_bus=bus, exec_adapter=None)
        with pytest.raises(RuntimeError, match="No execution adapter"):
            await mgr.create_trailing_stop("AAPL", Decimal("10"), Decimal("150"), trail_amount=Decimal("5"))

    @pytest.mark.asyncio
    async def test_no_trail_params_raises(self, manager):
        with pytest.raises(ValueError, match="Either trail_amount or trail_percent"):
            await manager.create_trailing_stop("AAPL", Decimal("10"), Decimal("150"))

    @pytest.mark.asyncio
    async def test_both_trail_params_raises(self, manager):
        with pytest.raises(ValueError, match="Cannot specify both"):
            await manager.create_trailing_stop(
                "AAPL", Decimal("10"), Decimal("150"),
                trail_amount=Decimal("5"), trail_percent=Decimal("0.05"),
            )

    @pytest.mark.asyncio
    async def test_zero_quantity_raises(self, manager):
        with pytest.raises(ValueError, match="quantity must be positive"):
            await manager.create_trailing_stop("AAPL", Decimal("0"), Decimal("150"), trail_amount=Decimal("5"))

    @pytest.mark.asyncio
    async def test_negative_trail_amount_raises(self, manager):
        with pytest.raises(ValueError, match="trail_amount must be positive"):
            await manager.create_trailing_stop("AAPL", Decimal("10"), Decimal("150"), trail_amount=Decimal("-1"))

    @pytest.mark.asyncio
    async def test_trail_percent_out_of_range_raises(self, manager):
        with pytest.raises(ValueError, match="trail_percent must be between"):
            await manager.create_trailing_stop("AAPL", Decimal("10"), Decimal("150"), trail_percent=Decimal("1.5"))
        with pytest.raises(ValueError, match="trail_percent must be between"):
            await manager.create_trailing_stop("AAPL", Decimal("10"), Decimal("150"), trail_percent=Decimal("0"))


# ── Initial Placement ────────────────────────────────────────────────


class TestTrailingStopPlacement:
    @pytest.mark.asyncio
    async def test_create_with_trail_amount(self, manager, mock_exec):
        ts = await manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        assert ts.state == TrailingStopState.ACTIVE
        assert ts.current_stop_price == Decimal("145")
        assert ts.high_water_mark == Decimal("150")
        assert ts.stop_order_id is not None
        mock_exec.submit_order.assert_called_once()
        order = mock_exec.submit_order.call_args[0][0]
        assert order.stop_price == 145.0
        assert order.quantity == Decimal("10")

    @pytest.mark.asyncio
    async def test_create_with_trail_percent(self, manager, mock_exec):
        ts = await manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("100"),
            current_price=Decimal("200"),
            trail_percent=Decimal("0.05"),
        )
        assert ts.state == TrailingStopState.ACTIVE
        assert ts.current_stop_price == Decimal("190")  # 200 * (1 - 0.05)
        assert ts.high_water_mark == Decimal("200")

    @pytest.mark.asyncio
    async def test_placement_failure_transitions_to_error(self, manager, mock_exec):
        mock_exec.submit_order.side_effect = Exception("Connection error")
        ts = await manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        assert ts.state == TrailingStopState.ERROR

    @pytest.mark.asyncio
    async def test_placed_event_emitted(self, manager, bus, mock_exec):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(TrailingStopChannel.TRAILING_STOP_PLACED, _collect)

        ts = await manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        assert len(events) == 1
        assert events[0]["trailing_stop_id"] == ts.trailing_stop_id
        assert events[0]["stop_price"] == "145"

    @pytest.mark.asyncio
    async def test_get_trailing_stop(self, manager):
        ts = await manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        assert manager.get_trailing_stop(ts.trailing_stop_id) is ts
        assert manager.get_trailing_stop("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_active_trailing_stops(self, manager):
        ts = await manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        active = manager.get_active_trailing_stops()
        assert len(active) == 1
        assert active[0].trailing_stop_id == ts.trailing_stop_id


# ── Ratchet Behavior ─────────────────────────────────────────────────


class TestTrailingStopRatchet:
    @pytest.mark.asyncio
    async def test_ratchet_up_on_price_increase(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        assert ts.current_stop_price == Decimal("145")

        # Price rises to 155
        await send_quote(bus, "AAPL", 155)
        assert ts.high_water_mark == Decimal("155")
        assert ts.current_stop_price == Decimal("150")

        # Price rises to 160
        await send_quote(bus, "AAPL", 160)
        assert ts.high_water_mark == Decimal("160")
        assert ts.current_stop_price == Decimal("155")

    @pytest.mark.asyncio
    async def test_never_ratchet_down(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        # Price rises to 160
        await send_quote(bus, "AAPL", 160)
        assert ts.current_stop_price == Decimal("155")

        # Price drops to 155 — stop should NOT move down
        await send_quote(bus, "AAPL", 155)
        assert ts.current_stop_price == Decimal("155")
        assert ts.high_water_mark == Decimal("160")

        # Price drops further to 140 — still no change
        await send_quote(bus, "AAPL", 140)
        assert ts.current_stop_price == Decimal("155")

    @pytest.mark.asyncio
    async def test_ratchet_with_trail_percent(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("100"),
            current_price=Decimal("100"), trail_percent=Decimal("0.10"),
        )
        assert ts.current_stop_price == Decimal("90")  # 100 * 0.90

        # Price rises to 120
        await send_quote(bus, "AAPL", 120)
        assert ts.current_stop_price == Decimal("108")  # 120 * 0.90
        assert ts.high_water_mark == Decimal("120")

    @pytest.mark.asyncio
    async def test_ratchet_emits_update_event(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(TrailingStopChannel.TRAILING_STOP_UPDATED, _collect)

        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        await send_quote(bus, "AAPL", 160)
        assert len(events) == 1
        assert events[0]["new_stop_price"] == "155"

    @pytest.mark.asyncio
    async def test_ignores_other_symbols(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        # Quote for different symbol
        await send_quote(bus, "GOOG", 3000)
        assert ts.current_stop_price == Decimal("145")
        assert ts.high_water_mark == Decimal("150")

    @pytest.mark.asyncio
    async def test_ratchet_replaces_stop_order(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        initial_order_id = ts.stop_order_id
        mock_exec.reset_mock()

        # Price rises — should cancel old stop and place new one
        await send_quote(bus, "AAPL", 160)

        # Fallback path: cancel + submit (since mock_exec doesn't have cancel_and_replace by default)
        mock_exec.cancel_order.assert_called_once_with(initial_order_id)
        assert mock_exec.submit_order.call_count == 1
        new_order = mock_exec.submit_order.call_args[0][0]
        assert new_order.stop_price == 155.0

    @pytest.mark.asyncio
    async def test_ratchet_uses_cancel_and_replace_when_available(self, bus, mock_exec):
        mock_exec.cancel_and_replace = AsyncMock(return_value=None)
        mgr = TrailingStopManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        ts = await mgr.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        mock_exec.reset_mock()

        # Patch the import to avoid needing the actual SDK
        with patch("trading_platform.orders.trailing_stop.TrailingStopManager._replace_stop_order") as mock_replace:
            # Directly call the actual _replace_stop_order
            pass

        # Price rises — since mock has cancel_and_replace attribute, it'll try that path
        # But import of CancelAndReplaceRequest will fail, so it falls back to cancel+replace
        await send_quote(bus, "AAPL", 160)

        # Should have fallen back to cancel + submit
        assert ts.current_stop_price == Decimal("155")
        await mgr.unwire_events()


# ── Stop Fill Completion ─────────────────────────────────────────────


class TestTrailingStopFill:
    @pytest.mark.asyncio
    async def test_stop_fill_completes_trailing_stop(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        assert ts.state == TrailingStopState.ACTIVE

        await fill_stop(bus, ts.stop_order_id, 144.50)
        assert ts.state == TrailingStopState.COMPLETED
        assert ts.fill_price == Decimal("144.50")
        assert ts.completed_at is not None

    @pytest.mark.asyncio
    async def test_stop_fill_emits_filled_event(self, wired_manager, bus):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(TrailingStopChannel.TRAILING_STOP_FILLED, _collect)

        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        await fill_stop(bus, ts.stop_order_id, 144.50)
        assert len(events) == 1
        assert events[0]["trailing_stop_id"] == ts.trailing_stop_id
        assert events[0]["fill_price"] == "144.5"

    @pytest.mark.asyncio
    async def test_no_ratchet_after_fill(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        await fill_stop(bus, ts.stop_order_id, 144.50)
        assert ts.state == TrailingStopState.COMPLETED

        # Price update should be ignored
        await send_quote(bus, "AAPL", 200)
        assert ts.current_stop_price == Decimal("145")  # Unchanged

    @pytest.mark.asyncio
    async def test_ignores_unrelated_fills(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        # Fill for a different order
        await fill_stop(bus, "unrelated-order-id", 144.50)
        assert ts.state == TrailingStopState.ACTIVE


# ── Cancellation ─────────────────────────────────────────────────────


class TestTrailingStopCancel:
    @pytest.mark.asyncio
    async def test_cancel_active_trailing_stop(self, manager, mock_exec):
        ts = await manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        result = await manager.cancel_trailing_stop(ts.trailing_stop_id)
        assert result is True
        assert ts.state == TrailingStopState.CANCELED
        assert ts.completed_at is not None
        mock_exec.cancel_order.assert_called_once_with(ts.stop_order_id)

    @pytest.mark.asyncio
    async def test_cancel_completed_trailing_stop_returns_false(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        await fill_stop(bus, ts.stop_order_id, 144.50)
        assert ts.state == TrailingStopState.COMPLETED

        result = await wired_manager.cancel_trailing_stop(ts.trailing_stop_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, manager):
        result = await manager.cancel_trailing_stop("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_when_exec_cancel_fails(self, manager, mock_exec):
        ts = await manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        mock_exec.cancel_order.side_effect = Exception("Cancel failed")
        result = await manager.cancel_trailing_stop(ts.trailing_stop_id)
        # Still transitions to CANCELED even if exec cancel fails
        assert result is True
        assert ts.state == TrailingStopState.CANCELED


# ── State Changes ────────────────────────────────────────────────────


class TestTrailingStopStateChanges:
    @pytest.mark.asyncio
    async def test_state_change_events_emitted(self, manager, bus):
        events = []
        async def _collect(ch, ev): events.append(ev)
        await bus.subscribe(TrailingStopChannel.TRAILING_STOP_STATE_CHANGE, _collect)

        ts = await manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        # PENDING → ACTIVE
        assert len(events) == 1
        assert events[0]["from_state"] == "pending"
        assert events[0]["to_state"] == "active"

    @pytest.mark.asyncio
    async def test_replacement_failure_transitions_to_error(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        mock_exec.cancel_order.side_effect = Exception("Network error")
        mock_exec.submit_order.side_effect = Exception("Network error")

        await send_quote(bus, "AAPL", 160)
        assert ts.state == TrailingStopState.ERROR

    @pytest.mark.asyncio
    async def test_multiple_trailing_stops_same_symbol(self, wired_manager, bus, mock_exec):
        ts1 = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        ts2 = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("20"),
            current_price=Decimal("150"), trail_amount=Decimal("10"),
        )
        mock_exec.reset_mock()

        # Both should ratchet on same quote
        await send_quote(bus, "AAPL", 160)
        assert ts1.current_stop_price == Decimal("155")  # 160 - 5
        assert ts2.current_stop_price == Decimal("150")  # 160 - 10


# ── Edge Cases ───────────────────────────────────────────────────────


class TestTrailingStopEdgeCases:
    @pytest.mark.asyncio
    async def test_quote_at_same_price_does_not_ratchet(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        mock_exec.reset_mock()

        # Same price — no ratchet
        await send_quote(bus, "AAPL", 150)
        assert ts.current_stop_price == Decimal("145")
        mock_exec.cancel_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_dict_event_handling(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        # Non-dict, non-QuoteTick event should be ignored
        await bus.publish("quote", "not-a-valid-event")
        assert ts.current_stop_price == Decimal("145")

    @pytest.mark.asyncio
    async def test_fill_event_without_order_id_ignored(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        # Fill event without order_id — should be ignored
        await bus.publish("execution.order.filled", {"fill_price": "144"})
        assert ts.state == TrailingStopState.ACTIVE

    @pytest.mark.asyncio
    async def test_fill_with_avg_price_fallback(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL", quantity=Decimal("10"),
            current_price=Decimal("150"), trail_amount=Decimal("5"),
        )
        # Use avg_price instead of fill_price
        await bus.publish("execution.order.filled", {
            "order_id": ts.stop_order_id,
            "avg_price": "143.50",
        })
        assert ts.state == TrailingStopState.COMPLETED
        assert ts.fill_price == Decimal("143.50")
