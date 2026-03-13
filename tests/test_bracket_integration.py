"""Integration tests for bracket orders with trailing stops and scaled exits."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.bracket.enums import BracketChannel, BracketState
from trading_platform.bracket.manager import BracketOrderManager
from trading_platform.core.enums import OrderType
from trading_platform.core.events import EventBus
from trading_platform.orders.trailing_stop import TrailingStopState


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
    return BracketOrderManager(event_bus=bus, exec_adapter=mock_exec)


@pytest.fixture
async def wired_manager(manager, bus):
    await manager.wire_events()
    yield manager
    await manager.unwire_events()


# ── Helpers ───────────────────────────────────────────────────────────


async def fill_entry(bus, bracket):
    await bus.publish("execution.order.filled", {
        "order_id": bracket.entry_order_id,
        "fill_price": "150.00",
    })


async def send_quote(bus, symbol, bid_price):
    await bus.publish("quote", {"symbol": symbol, "bid_price": str(bid_price)})


# ── Tests: Bracket with Trailing Stop ─────────────────────────────────


class TestBracketTrailingStop:

    @pytest.mark.asyncio
    async def test_submit_with_trailing_stop(self, wired_manager, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        assert bracket.trailing_stop is True
        assert bracket.trail_amount == Decimal("5")
        assert bracket.state == BracketState.ENTRY_PLACED

    @pytest.mark.asyncio
    async def test_trailing_stop_activated_on_entry_fill(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING
        assert bracket.trailing_stop_id is not None

        # Verify trailing stop is active
        ts = wired_manager._trailing_stop_mgr.get_trailing_stop(bracket.trailing_stop_id)
        assert ts is not None
        assert ts.state == TrailingStopState.ACTIVE
        assert ts.current_stop_price == Decimal("145")  # 150 - 5

    @pytest.mark.asyncio
    async def test_trailing_stop_ratchets_with_quotes(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        await fill_entry(bus, bracket)
        ts = wired_manager._trailing_stop_mgr.get_trailing_stop(bracket.trailing_stop_id)

        # Price rises
        await send_quote(bus, "AAPL", "155")
        assert ts.current_stop_price == Decimal("150")

        await send_quote(bus, "AAPL", "160")
        assert ts.current_stop_price == Decimal("155")

        # Price drops — stop stays
        await send_quote(bus, "AAPL", "157")
        assert ts.current_stop_price == Decimal("155")

    @pytest.mark.asyncio
    async def test_trailing_stop_fill_stops_bracket(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        await fill_entry(bus, bracket)
        ts = wired_manager._trailing_stop_mgr.get_trailing_stop(bracket.trailing_stop_id)

        # Simulate trailing stop order fill
        await bus.publish("execution.order.filled", {
            "order_id": ts.stop_order_id,
            "fill_price": "144.50",
        })

        assert ts.state == TrailingStopState.COMPLETED
        assert bracket.state == BracketState.STOPPED_OUT
        assert bracket.exit_fill_price == Decimal("144.50")

    @pytest.mark.asyncio
    async def test_trailing_stop_with_percent(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            trailing_stop=True,
            trail_percent=Decimal("0.05"),
        )
        await fill_entry(bus, bracket)
        ts = wired_manager._trailing_stop_mgr.get_trailing_stop(bracket.trailing_stop_id)
        # 150 * (1 - 0.05) = 142.50
        assert ts.current_stop_price == Decimal("142.50")

    @pytest.mark.asyncio
    async def test_trailing_stop_take_profit_still_works(self, wired_manager, bus, mock_exec):
        """When trailing stop is active, standard take-profit monitoring still fires."""
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING

        # Bid reaches take-profit → triggers take-profit flow
        await send_quote(bus, "AAPL", "160")
        assert bracket.state == BracketState.TAKE_PROFIT_TRIGGERED

    @pytest.mark.asyncio
    async def test_cancel_bracket_with_trailing_stop(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        await fill_entry(bus, bracket)
        ts = wired_manager._trailing_stop_mgr.get_trailing_stop(bracket.trailing_stop_id)
        assert ts.state == TrailingStopState.ACTIVE

        result = await wired_manager.cancel_bracket(bracket.bracket_id)
        assert result is True
        assert bracket.state == BracketState.CANCELED
        assert ts.state == TrailingStopState.CANCELED


# ── Tests: Bracket with Trailing Stop Validation ──────────────────────


class TestBracketTrailingStopValidation:

    @pytest.mark.asyncio
    async def test_trailing_stop_requires_trail_param(self, wired_manager):
        with pytest.raises(ValueError, match="requires trail_amount or trail_percent"):
            await wired_manager.submit_bracket_order(
                symbol="AAPL",
                quantity=Decimal("10"),
                entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("140"),
                take_profit_price=Decimal("160"),
                trailing_stop=True,
            )

    @pytest.mark.asyncio
    async def test_trailing_stop_both_params_raises(self, wired_manager):
        with pytest.raises(ValueError, match="not both"):
            await wired_manager.submit_bracket_order(
                symbol="AAPL",
                quantity=Decimal("10"),
                entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("140"),
                take_profit_price=Decimal("160"),
                trailing_stop=True,
                trail_amount=Decimal("5"),
                trail_percent=Decimal("0.05"),
            )


# ── Tests: Bracket with Scaled Exits ─────────────────────────────────


class TestBracketScaledExits:

    @pytest.mark.asyncio
    async def test_submit_with_scaled_exits(self, wired_manager, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
        )
        assert bracket.take_profit_levels is not None
        assert len(bracket.take_profit_levels) == 2
        assert bracket.state == BracketState.ENTRY_PLACED

    @pytest.mark.asyncio
    async def test_scaled_exit_activated_on_entry_fill(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING
        assert bracket.scaled_exit_id is not None

        scaled = wired_manager._scaled_order_mgr.get_scaled_exit(bracket.scaled_exit_id)
        assert scaled is not None

    @pytest.mark.asyncio
    async def test_scaled_exit_completes_bracket(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(BracketChannel.BRACKET_TAKE_PROFIT_FILLED, _collect)

        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        # Trigger both tranches
        await send_quote(bus, "AAPL", "160")
        await send_quote(bus, "AAPL", "170")

        assert bracket.state == BracketState.TAKE_PROFIT_FILLED
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_scaled_exit_stop_out(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)
        scaled = wired_manager._scaled_order_mgr.get_scaled_exit(bracket.scaled_exit_id)

        # Stop fills before any tranche
        await bus.publish("execution.order.filled", {
            "order_id": scaled.stop_order_id,
            "fill_price": "139.50",
        })
        assert bracket.state == BracketState.STOPPED_OUT

    @pytest.mark.asyncio
    async def test_scaled_exit_partial_then_stop(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)
        scaled = wired_manager._scaled_order_mgr.get_scaled_exit(bracket.scaled_exit_id)

        # First tranche fills
        await send_quote(bus, "AAPL", "160")

        # Stop fills
        await bus.publish("execution.order.filled", {
            "order_id": scaled.stop_order_id,
            "fill_price": "139",
        })
        assert bracket.state == BracketState.STOPPED_OUT


# ── Tests: Bracket with Trailing Stop + Scaled Exits ──────────────────


class TestBracketTrailingAndScaled:

    @pytest.mark.asyncio
    async def test_combined_trailing_and_scaled(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING
        assert bracket.trailing_stop_id is not None
        assert bracket.scaled_exit_id is not None

    @pytest.mark.asyncio
    async def test_scaled_complete_cancels_trailing(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("170"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
            take_profit_levels=[
                (Decimal("160"), Decimal("0.5")),
                (Decimal("170"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)
        ts = wired_manager._trailing_stop_mgr.get_trailing_stop(bracket.trailing_stop_id)

        # All tranches fill
        await send_quote(bus, "AAPL", "160")
        await send_quote(bus, "AAPL", "170")

        assert bracket.state == BracketState.TAKE_PROFIT_FILLED
        assert ts.state == TrailingStopState.CANCELED


# ── Tests: Backward Compatibility ─────────────────────────────────────


class TestBracketBackwardCompatibility:

    @pytest.mark.asyncio
    async def test_standard_bracket_still_works(self, wired_manager, bus, mock_exec):
        """Existing behavior should be unchanged."""
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
        )
        assert bracket.trailing_stop is False
        assert bracket.take_profit_levels is None

        await fill_entry(bus, bracket)
        assert bracket.state == BracketState.MONITORING
        assert bracket.stop_loss_order_id is not None
        assert bracket.trailing_stop_id is None
        assert bracket.scaled_exit_id is None

    @pytest.mark.asyncio
    async def test_standard_stop_loss_fills(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
        )
        await fill_entry(bus, bracket)

        await bus.publish("execution.order.filled", {
            "order_id": bracket.stop_loss_order_id,
            "fill_price": "139.50",
        })
        assert bracket.state == BracketState.STOPPED_OUT

    @pytest.mark.asyncio
    async def test_standard_take_profit(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
        )
        await fill_entry(bus, bracket)

        await send_quote(bus, "AAPL", "160")
        assert bracket.state == BracketState.TAKE_PROFIT_TRIGGERED


# ── Tests: Events ─────────────────────────────────────────────────────


class TestBracketIntegrationEvents:

    @pytest.mark.asyncio
    async def test_stopped_out_event(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(BracketChannel.BRACKET_STOPPED_OUT, _collect)

        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        await fill_entry(bus, bracket)
        ts = wired_manager._trailing_stop_mgr.get_trailing_stop(bracket.trailing_stop_id)

        await bus.publish("execution.order.filled", {
            "order_id": ts.stop_order_id,
            "fill_price": "144.50",
        })
        assert len(events) == 1
        assert events[0]["bracket_id"] == bracket.bracket_id

    @pytest.mark.asyncio
    async def test_stop_placed_event_with_trailing(self, wired_manager, bus, mock_exec):
        events = []
        async def _collect(c, e): events.append(e)
        await bus.subscribe(BracketChannel.BRACKET_STOP_PLACED, _collect)

        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        await fill_entry(bus, bracket)
        assert len(events) == 1
        assert "trailing_stop_id" in events[0]
