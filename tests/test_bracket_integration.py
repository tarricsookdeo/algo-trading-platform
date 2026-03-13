"""Integration tests: bracket orders with trailing stops and scaled exits."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.bracket.enums import BracketChannel, BracketState
from trading_platform.bracket.manager import BracketOrderManager
from trading_platform.core.enums import OrderType
from trading_platform.core.events import EventBus


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
    await bus.publish("quote", {
        "symbol": symbol,
        "bid_price": bid_price,
        "ask_price": bid_price + 0.01,
        "bid_size": 100,
        "ask_size": 100,
    })


# ── Bracket + Trailing Stop ──────────────────────────────────────────


class TestBracketWithTrailingStop:
    @pytest.mark.asyncio
    async def test_trailing_stop_bracket_submission(self, wired_manager, bus, mock_exec):
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
    async def test_trailing_stop_validation_requires_trail_params(self, wired_manager):
        with pytest.raises(ValueError, match="trailing_stop requires"):
            await wired_manager.submit_bracket_order(
                symbol="AAPL",
                quantity=Decimal("10"),
                entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("140"),
                take_profit_price=Decimal("160"),
                trailing_stop=True,
            )

    @pytest.mark.asyncio
    async def test_trailing_stop_validation_no_both_params(self, wired_manager):
        with pytest.raises(ValueError, match="Cannot specify both"):
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

    @pytest.mark.asyncio
    async def test_trailing_stop_placed_after_entry_fill(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
        )
        mock_exec.reset_mock()

        # Fill entry
        await fill_entry(bus, bracket)

        # Should now have trailing stop placed (submit_order called for stop)
        assert bracket.state == BracketState.MONITORING
        assert bracket.trailing_stop_id is not None
        assert bracket.stop_loss_order_id is not None
        # The trailing stop manager should have submitted a stop order
        mock_exec.submit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_trailing_stop_ratchets_up(self, wired_manager, bus, mock_exec):
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
        mock_exec.reset_mock()

        # Get the trailing stop manager's order to check ratchet
        ts_mgr = wired_manager._trailing_stop_mgr
        ts = ts_mgr.get_trailing_stop(bracket.trailing_stop_id)
        initial_stop = ts.current_stop_price

        # Price rises
        await send_quote(bus, "AAPL", 155)
        assert ts.current_stop_price > initial_stop

    @pytest.mark.asyncio
    async def test_trailing_stop_fill_stops_out_bracket(self, wired_manager, bus, mock_exec):
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

        ts_mgr = wired_manager._trailing_stop_mgr
        ts = ts_mgr.get_trailing_stop(bracket.trailing_stop_id)

        # Simulate the stop order filling
        await bus.publish("execution.order.filled", {
            "order_id": ts.stop_order_id,
            "fill_price": "145.00",
        })

        # The trailing stop manager handles this and publishes trailing_stop.filled
        # Which the bracket manager picks up
        assert bracket.state == BracketState.STOPPED_OUT
        assert bracket.exit_fill_price == Decimal("145.00")

    @pytest.mark.asyncio
    async def test_trailing_stop_bracket_cancel(self, wired_manager, bus, mock_exec):
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

        result = await wired_manager.cancel_bracket(bracket.bracket_id)
        assert result is True
        assert bracket.state == BracketState.CANCELED

    @pytest.mark.asyncio
    async def test_trailing_stop_with_percent(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("10"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("160"),
            trailing_stop=True,
            trail_percent=Decimal("0.05"),
        )
        await fill_entry(bus, bracket)

        ts_mgr = wired_manager._trailing_stop_mgr
        ts = ts_mgr.get_trailing_stop(bracket.trailing_stop_id)
        # Initial stop: 150 * (1 - 0.05) = 142.50
        assert ts.current_stop_price == Decimal("142.50")

    @pytest.mark.asyncio
    async def test_take_profit_still_works_with_trailing_stop(self, wired_manager, bus, mock_exec):
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

        # Price reaches take-profit level
        await send_quote(bus, "AAPL", 160)
        # The bracket manager should trigger take-profit
        assert bracket.state == BracketState.TAKE_PROFIT_TRIGGERED


# ── Bracket + Scaled Exits ───────────────────────────────────────────


class TestBracketWithScaledExits:
    @pytest.mark.asyncio
    async def test_scaled_exit_bracket_submission(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        assert bracket.take_profit_levels is not None
        assert len(bracket.take_profit_levels) == 2

    @pytest.mark.asyncio
    async def test_scaled_exit_validation(self, wired_manager):
        with pytest.raises(ValueError, match="percentages must sum to 1.0"):
            await wired_manager.submit_bracket_order(
                symbol="AAPL",
                quantity=Decimal("100"),
                entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("140"),
                take_profit_price=Decimal("165"),
                take_profit_levels=[
                    (Decimal("155"), Decimal("0.3")),
                    (Decimal("160"), Decimal("0.3")),
                ],
            )

    @pytest.mark.asyncio
    async def test_scaled_exits_setup_after_entry_fill(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        assert bracket.state == BracketState.MONITORING
        assert bracket.scaled_order_id is not None
        assert wired_manager._scaled_order_mgr is not None

    @pytest.mark.asyncio
    async def test_scaled_exit_skips_single_take_profit(self, wired_manager, bus, mock_exec):
        """Brackets with take_profit_levels skip the normal TP trigger in _on_quote."""
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        # Price reaches the single TP price — but bracket has scaled exits, so
        # the bracket manager's _on_quote should NOT trigger single TP
        await send_quote(bus, "AAPL", 165)
        assert bracket.state == BracketState.MONITORING  # NOT TAKE_PROFIT_TRIGGERED

    @pytest.mark.asyncio
    async def test_scaled_exit_tranche_triggers(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)
        mock_exec.reset_mock()

        # Price reaches first tranche
        await send_quote(bus, "AAPL", 155)
        # ScaledOrderManager should have submitted a sell order
        assert mock_exec.submit_order.call_count >= 1

    @pytest.mark.asyncio
    async def test_all_scaled_exits_complete_bracket(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        scaled_mgr = wired_manager._scaled_order_mgr
        scaled = scaled_mgr.get_scaled_exit(bracket.scaled_order_id)

        # Trigger and fill first tranche
        await send_quote(bus, "AAPL", 155)
        await bus.publish("execution.order.filled", {
            "order_id": scaled.tranches[0].order_id,
            "fill_price": "155.25",
        })

        # Trigger and fill second tranche
        await send_quote(bus, "AAPL", 160)
        await bus.publish("execution.order.filled", {
            "order_id": scaled.tranches[1].order_id,
            "fill_price": "160.50",
        })

        # Bracket should be completed via scaled_exit.completed event
        assert bracket.state == BracketState.TAKE_PROFIT_FILLED

    @pytest.mark.asyncio
    async def test_bracket_stopped_out_with_scaled_exits(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        # Stop-loss fills before any tranche
        await bus.publish("execution.order.filled", {
            "order_id": bracket.stop_loss_order_id,
            "fill_price": "139.50",
        })
        assert bracket.state == BracketState.STOPPED_OUT

    @pytest.mark.asyncio
    async def test_cancel_bracket_with_scaled_exits(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        result = await wired_manager.cancel_bracket(bracket.bracket_id)
        assert result is True
        assert bracket.state == BracketState.CANCELED


# ── Bracket + Trailing Stop + Scaled Exits ───────────────────────────


class TestBracketFullIntegration:
    @pytest.mark.asyncio
    async def test_trailing_stop_with_scaled_exits(self, wired_manager, bus, mock_exec):
        """Full integration: trailing stop + scaled exits on same bracket."""
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        assert bracket.state == BracketState.MONITORING
        assert bracket.trailing_stop_id is not None
        assert bracket.scaled_order_id is not None

        # Verify trailing stop is active
        ts_mgr = wired_manager._trailing_stop_mgr
        ts = ts_mgr.get_trailing_stop(bracket.trailing_stop_id)
        assert ts.state.value == "active"

        # Verify scaled exits are active
        scaled_mgr = wired_manager._scaled_order_mgr
        scaled = scaled_mgr.get_scaled_exit(bracket.scaled_order_id)
        assert scaled.state.value == "active"

    @pytest.mark.asyncio
    async def test_trailing_stop_ratchets_while_scaled_exits_trigger(self, wired_manager, bus, mock_exec):
        bracket = await wired_manager.submit_bracket_order(
            symbol="AAPL",
            quantity=Decimal("100"),
            entry_type=OrderType.MARKET,
            stop_loss_price=Decimal("140"),
            take_profit_price=Decimal("165"),
            trailing_stop=True,
            trail_amount=Decimal("5"),
            take_profit_levels=[
                (Decimal("155"), Decimal("0.5")),
                (Decimal("160"), Decimal("0.5")),
            ],
        )
        await fill_entry(bus, bracket)

        ts_mgr = wired_manager._trailing_stop_mgr
        ts = ts_mgr.get_trailing_stop(bracket.trailing_stop_id)
        initial_stop = ts.current_stop_price

        # Price rises to 155 — triggers first tranche AND ratchets trailing stop
        await send_quote(bus, "AAPL", 155)
        assert ts.current_stop_price > initial_stop

        # Scaled exit tranche should have been triggered too
        scaled_mgr = wired_manager._scaled_order_mgr
        scaled = scaled_mgr.get_scaled_exit(bracket.scaled_order_id)
        assert scaled.tranches[0].order_id is not None  # Order was placed
