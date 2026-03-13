"""Comprehensive tests for the trailing stop order manager."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.core.events import EventBus
from trading_platform.orders.trailing_stop import (
    TRAILING_STOP_TERMINAL_STATES,
    TrailingStop,
    TrailingStopChannel,
    TrailingStopManager,
    TrailingStopState,
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
    # Ensure cancel_and_replace is not available by default
    del exec_adapter.cancel_and_replace
    return exec_adapter


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
    """Publish a quote event."""
    await bus.publish("quote", {"symbol": symbol, "bid_price": str(bid_price)})


async def fill_stop(bus, order_id, fill_price):
    """Simulate stop order fill."""
    await bus.publish("execution.order.filled", {
        "order_id": order_id,
        "fill_price": str(fill_price),
    })


async def cancel_order_event(bus, order_id):
    """Simulate order cancellation."""
    await bus.publish("execution.order.cancelled", {"order_id": order_id})


# ── Tests: Creation & Validation ──────────────────────────────────────


class TestTrailingStopCreation:

    @pytest.mark.asyncio
    async def test_create_with_trail_amount(self, wired_manager, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        assert ts.symbol == "AAPL"
        assert ts.quantity == Decimal("10")
        assert ts.trail_amount == Decimal("5")
        assert ts.trail_percent is None
        assert ts.current_stop_price == Decimal("145")
        assert ts.highest_price == Decimal("150")
        assert ts.state == TrailingStopState.ACTIVE
        mock_exec.submit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_trail_percent(self, wired_manager, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("200"),
            trail_percent=Decimal("0.05"),
        )
        assert ts.current_stop_price == Decimal("190")  # 200 * 0.95
        assert ts.state == TrailingStopState.ACTIVE

    @pytest.mark.asyncio
    async def test_no_trail_param_raises(self, wired_manager):
        with pytest.raises(ValueError, match="Must provide trail_amount or trail_percent"):
            await wired_manager.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("150"),
            )

    @pytest.mark.asyncio
    async def test_both_trail_params_raises(self, wired_manager):
        with pytest.raises(ValueError, match="not both"):
            await wired_manager.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("150"),
                trail_amount=Decimal("5"),
                trail_percent=Decimal("0.05"),
            )

    @pytest.mark.asyncio
    async def test_negative_trail_amount_raises(self, wired_manager):
        with pytest.raises(ValueError, match="trail_amount must be positive"):
            await wired_manager.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("150"),
                trail_amount=Decimal("-1"),
            )

    @pytest.mark.asyncio
    async def test_zero_trail_amount_raises(self, wired_manager):
        with pytest.raises(ValueError, match="trail_amount must be positive"):
            await wired_manager.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("150"),
                trail_amount=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_invalid_trail_percent_raises(self, wired_manager):
        with pytest.raises(ValueError, match="trail_percent must be between"):
            await wired_manager.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("150"),
                trail_percent=Decimal("1.5"),
            )

    @pytest.mark.asyncio
    async def test_zero_trail_percent_raises(self, wired_manager):
        with pytest.raises(ValueError, match="trail_percent must be between"):
            await wired_manager.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("150"),
                trail_percent=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_negative_quantity_raises(self, wired_manager):
        with pytest.raises(ValueError, match="quantity must be positive"):
            await wired_manager.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("-5"),
                current_price=Decimal("150"),
                trail_amount=Decimal("5"),
            )

    @pytest.mark.asyncio
    async def test_no_exec_adapter_raises(self, bus):
        mgr = TrailingStopManager(event_bus=bus, exec_adapter=None)
        with pytest.raises(RuntimeError, match="No execution adapter"):
            await mgr.create_trailing_stop(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("150"),
                trail_amount=Decimal("5"),
            )


# ── Tests: Ratchet Logic ─────────────────────────────────────────────


class TestTrailingStopRatchet:

    @pytest.mark.asyncio
    async def test_ratchet_up_on_new_high(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        assert ts.current_stop_price == Decimal("145")

        # Price rises to 155 → stop should move to 150
        await send_quote(bus, "AAPL", "155")
        assert ts.current_stop_price == Decimal("150")
        assert ts.highest_price == Decimal("155")
        # Should have called cancel_order + submit_order for the replacement
        assert mock_exec.submit_order.call_count >= 2

    @pytest.mark.asyncio
    async def test_never_ratchet_down(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        # Price rises
        await send_quote(bus, "AAPL", "160")
        assert ts.current_stop_price == Decimal("155")

        # Price drops — stop should NOT move down
        await send_quote(bus, "AAPL", "152")
        assert ts.current_stop_price == Decimal("155")
        assert ts.highest_price == Decimal("160")

    @pytest.mark.asyncio
    async def test_ratchet_with_percent(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("100"),
            trail_percent=Decimal("0.10"),
        )
        assert ts.current_stop_price == Decimal("90")  # 100 * 0.90

        # Price rises to 120
        await send_quote(bus, "AAPL", "120")
        assert ts.current_stop_price == Decimal("108")  # 120 * 0.90
        assert ts.highest_price == Decimal("120")

    @pytest.mark.asyncio
    async def test_equal_price_no_update(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        initial_call_count = mock_exec.submit_order.call_count

        # Same price — no update
        await send_quote(bus, "AAPL", "150")
        assert mock_exec.submit_order.call_count == initial_call_count

    @pytest.mark.asyncio
    async def test_different_symbol_ignored(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        initial_call_count = mock_exec.submit_order.call_count

        await send_quote(bus, "GOOG", "300")
        assert mock_exec.submit_order.call_count == initial_call_count
        assert ts.current_stop_price == Decimal("145")

    @pytest.mark.asyncio
    async def test_multiple_ratchets(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("100"),
            trail_amount=Decimal("10"),
        )
        assert ts.current_stop_price == Decimal("90")

        await send_quote(bus, "AAPL", "110")
        assert ts.current_stop_price == Decimal("100")

        await send_quote(bus, "AAPL", "120")
        assert ts.current_stop_price == Decimal("110")

        await send_quote(bus, "AAPL", "130")
        assert ts.current_stop_price == Decimal("120")


# ── Tests: Stop Fill ──────────────────────────────────────────────────


class TestTrailingStopFill:

    @pytest.mark.asyncio
    async def test_stop_fill_completes(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        assert ts.state == TrailingStopState.ACTIVE

        await fill_stop(bus, ts.stop_order_id, "144.50")
        assert ts.state == TrailingStopState.COMPLETED
        assert ts.exit_fill_price == Decimal("144.50")
        assert ts.completed_at is not None

    @pytest.mark.asyncio
    async def test_stop_fill_emits_event(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(TrailingStopChannel.TRAILING_STOP_COMPLETED, _collect)

        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        await fill_stop(bus, ts.stop_order_id, "144.50")

        assert len(events) == 1
        assert events[0]["trailing_stop_id"] == ts.trailing_stop_id
        assert events[0]["exit_price"] == "144.50"


# ── Tests: Cancellation ──────────────────────────────────────────────


class TestTrailingStopCancel:

    @pytest.mark.asyncio
    async def test_cancel_active_stop(self, wired_manager, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        result = await wired_manager.cancel_trailing_stop(ts.trailing_stop_id)
        assert result is True
        assert ts.state == TrailingStopState.CANCELED
        mock_exec.cancel_order.assert_called()

    @pytest.mark.asyncio
    async def test_cancel_completed_returns_false(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        await fill_stop(bus, ts.stop_order_id, "144.50")
        assert ts.state == TrailingStopState.COMPLETED

        result = await wired_manager.cancel_trailing_stop(ts.trailing_stop_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, wired_manager):
        result = await wired_manager.cancel_trailing_stop("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_external_cancel_transitions(self, wired_manager, bus):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        # External cancellation of the stop order
        await cancel_order_event(bus, ts.stop_order_id)
        assert ts.state == TrailingStopState.CANCELED


# ── Tests: Query ──────────────────────────────────────────────────────


class TestTrailingStopQuery:

    @pytest.mark.asyncio
    async def test_get_trailing_stop(self, wired_manager):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        found = wired_manager.get_trailing_stop(ts.trailing_stop_id)
        assert found is ts

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, wired_manager):
        assert wired_manager.get_trailing_stop("nope") is None

    @pytest.mark.asyncio
    async def test_get_active_trailing_stops(self, wired_manager, bus):
        ts1 = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        ts2 = await wired_manager.create_trailing_stop(
            symbol="GOOG",
            quantity=Decimal("5"),
            current_price=Decimal("300"),
            trail_amount=Decimal("10"),
        )
        active = wired_manager.get_active_trailing_stops()
        assert len(active) == 2

        # Complete one
        await fill_stop(bus, ts1.stop_order_id, "144")
        active = wired_manager.get_active_trailing_stops()
        assert len(active) == 1
        assert active[0].trailing_stop_id == ts2.trailing_stop_id


# ── Tests: Error Handling ─────────────────────────────────────────────


class TestTrailingStopErrors:

    @pytest.mark.asyncio
    async def test_stop_placement_failure(self, bus, mock_exec):
        mock_exec.submit_order = AsyncMock(side_effect=Exception("network error"))
        mgr = TrailingStopManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        ts = await mgr.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        assert ts.state == TrailingStopState.ERROR

        await mgr.unwire_events()

    @pytest.mark.asyncio
    async def test_cancel_failure_during_replace(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        # Make cancel fail — stop price should revert
        mock_exec.cancel_order = AsyncMock(side_effect=Exception("cancel failed"))
        old_stop = ts.current_stop_price

        await send_quote(bus, "AAPL", "160")
        assert ts.current_stop_price == old_stop  # Reverted

    @pytest.mark.asyncio
    async def test_no_update_after_completion(self, wired_manager, bus, mock_exec):
        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        await fill_stop(bus, ts.stop_order_id, "144.50")
        initial_call_count = mock_exec.submit_order.call_count

        await send_quote(bus, "AAPL", "200")
        assert mock_exec.submit_order.call_count == initial_call_count


# ── Tests: Wiring ─────────────────────────────────────────────────────


class TestTrailingStopWiring:

    @pytest.mark.asyncio
    async def test_wire_and_unwire(self, manager, bus):
        await manager.wire_events()
        assert bus.subscriber_count > 0
        await manager.unwire_events()

    @pytest.mark.asyncio
    async def test_state_change_events(self, wired_manager, bus):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(
            TrailingStopChannel.TRAILING_STOP_STATE_CHANGE,
            _collect,
        )

        ts = await wired_manager.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )

        # PENDING → ACTIVE
        assert any(
            e["to_state"] == str(TrailingStopState.ACTIVE)
            for e in events
        )


# ── Tests: Cancel-and-Replace Path ───────────────────────────────────


class TestTrailingStopCancelAndReplace:

    @pytest.mark.asyncio
    async def test_uses_cancel_and_replace_when_available(self, bus):
        mock_exec = AsyncMock()
        mock_exec.submit_order = AsyncMock(return_value=None)
        mock_exec.cancel_order = AsyncMock(return_value=None)

        replace_result = AsyncMock()
        replace_result.order_id = "new-order-123"
        mock_exec.cancel_and_replace = AsyncMock(return_value=replace_result)

        mgr = TrailingStopManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        ts = await mgr.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )
        old_order_id = ts.stop_order_id

        await send_quote(bus, "AAPL", "160")
        mock_exec.cancel_and_replace.assert_called_once()
        assert ts.stop_order_id == "new-order-123"
        assert ts.stop_order_id != old_order_id

        await mgr.unwire_events()

    @pytest.mark.asyncio
    async def test_fallback_when_cancel_and_replace_fails(self, bus):
        mock_exec = AsyncMock()
        mock_exec.submit_order = AsyncMock(return_value=None)
        mock_exec.cancel_order = AsyncMock(return_value=None)
        mock_exec.cancel_and_replace = AsyncMock(side_effect=Exception("not supported"))

        mgr = TrailingStopManager(event_bus=bus, exec_adapter=mock_exec)
        await mgr.wire_events()

        ts = await mgr.create_trailing_stop(
            symbol="AAPL",
            quantity=Decimal("10"),
            current_price=Decimal("150"),
            trail_amount=Decimal("5"),
        )

        await send_quote(bus, "AAPL", "160")
        # Should have fallen through to manual cancel + replace
        mock_exec.cancel_order.assert_called()
        assert ts.current_stop_price == Decimal("155")

        await mgr.unwire_events()


# ── Tests: Dataclass & Enums ─────────────────────────────────────────


class TestTrailingStopModels:

    def test_terminal_states(self):
        assert TrailingStopState.COMPLETED in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.CANCELED in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.ERROR in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.ACTIVE not in TRAILING_STOP_TERMINAL_STATES
        assert TrailingStopState.PENDING not in TRAILING_STOP_TERMINAL_STATES

    def test_trailing_stop_dataclass(self):
        ts = TrailingStop(
            trailing_stop_id="test-1",
            symbol="AAPL",
            quantity=Decimal("10"),
            trail_amount=Decimal("5"),
            current_stop_price=Decimal("145"),
            highest_price=Decimal("150"),
        )
        assert ts.trailing_stop_id == "test-1"
        assert ts.state == TrailingStopState.PENDING
        assert ts.exit_fill_price is None
        assert ts.completed_at is None

    def test_channel_values(self):
        assert TrailingStopChannel.TRAILING_STOP_PLACED == "trailing_stop.placed"
        assert TrailingStopChannel.TRAILING_STOP_COMPLETED == "trailing_stop.completed"
