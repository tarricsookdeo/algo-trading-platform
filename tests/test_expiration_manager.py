"""Tests for ExpirationManager — DTE monitoring, auto-close, alerts, rolling."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_platform.core.enums import AssetClass, ContractType, OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.options.expiration import (
    EXPIRATION_WARNING,
    ExpirationConfig,
    ExpirationManager,
    OptionsPosition,
    POSITION_AUTO_CLOSED,
    POSITION_ROLLED,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def config():
    return ExpirationConfig(
        auto_close_dte=1,
        alert_dte=7,
        roll_enabled=False,
        roll_target_dte=30,
        check_interval_seconds=60.0,
    )


@pytest.fixture
def exec_adapter():
    adapter = AsyncMock()
    adapter.submit_order = AsyncMock()
    return adapter


@pytest.fixture
def manager(config, bus, exec_adapter):
    return ExpirationManager(
        config=config,
        event_bus=bus,
        exec_adapter=exec_adapter,
    )


def _pos(
    symbol: str = "AAPL240119C00150000",
    underlying: str = "AAPL",
    quantity: float = 10.0,
    contract_type: ContractType = ContractType.CALL,
    strike: float = 150.0,
    expiration: date | None = None,
) -> OptionsPosition:
    return OptionsPosition(
        symbol=symbol,
        underlying=underlying,
        quantity=quantity,
        contract_type=contract_type,
        strike_price=strike,
        expiration_date=expiration or date.today() + timedelta(days=30),
    )


# ── ExpirationConfig / OptionsPosition models ──────────────────────────


class TestExpirationConfig:
    def test_defaults(self):
        c = ExpirationConfig()
        assert c.auto_close_dte == 1
        assert c.alert_dte == 7
        assert c.roll_enabled is False
        assert c.roll_target_dte == 30
        assert c.check_interval_seconds == 60.0


class TestOptionsPosition:
    def test_creation(self):
        p = _pos()
        assert p.symbol == "AAPL240119C00150000"
        assert p.underlying == "AAPL"
        assert p.quantity == 10.0
        assert p.contract_type == ContractType.CALL


# ── ExpirationManager.set_positions ─────────────────────────────────────


class TestSetPositions:
    def test_set_positions(self, manager):
        positions = [_pos(), _pos(symbol="TSLA240119P00200000")]
        manager.set_positions(positions)
        assert len(manager._positions) == 2

    def test_replaces_positions(self, manager):
        manager.set_positions([_pos()])
        manager.set_positions([_pos(symbol="A"), _pos(symbol="B"), _pos(symbol="C")])
        assert len(manager._positions) == 3


# ── ExpirationManager.check_expirations — alert ────────────────────────


class TestAlertDTE:
    @pytest.mark.asyncio
    async def test_alert_at_threshold(self, manager, bus):
        """Position at alert_dte triggers warning event."""
        received = []

        async def handler(ch, ev):
            received.append((ch, ev))

        await bus.subscribe(EXPIRATION_WARNING, handler)

        today = date(2024, 1, 12)
        pos = _pos(expiration=date(2024, 1, 19))  # DTE = 7
        manager.set_positions([pos])
        await manager.check_expirations(today=today)

        assert len(received) == 1
        assert received[0][1]["dte"] == 7
        assert received[0][1]["symbol"] == pos.symbol

    @pytest.mark.asyncio
    async def test_no_alert_when_above_threshold(self, manager, bus):
        """Position with DTE > alert_dte → no warning."""
        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe(EXPIRATION_WARNING, handler)

        today = date(2024, 1, 1)
        pos = _pos(expiration=date(2024, 1, 19))  # DTE = 18
        manager.set_positions([pos])
        await manager.check_expirations(today=today)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_alert_not_duplicated(self, manager, bus):
        """Same symbol is only alerted once."""
        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe(EXPIRATION_WARNING, handler)

        today = date(2024, 1, 15)
        pos = _pos(expiration=date(2024, 1, 19))  # DTE = 4
        manager.set_positions([pos])
        await manager.check_expirations(today=today)
        await manager.check_expirations(today=today)

        assert len(received) == 1  # only one alert


# ── ExpirationManager.check_expirations — auto-close ──────────────────


class TestAutoClose:
    @pytest.mark.asyncio
    async def test_auto_close_at_threshold(self, manager, bus, exec_adapter):
        """Position at auto_close_dte triggers close order and event."""
        received = []

        async def handler(ch, ev):
            received.append((ch, ev))

        await bus.subscribe(POSITION_AUTO_CLOSED, handler)

        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19), quantity=10.0)  # DTE = 1
        manager.set_positions([pos])
        await manager.check_expirations(today=today)

        # Close order submitted
        exec_adapter.submit_order.assert_called_once()
        close_order = exec_adapter.submit_order.call_args[0][0]
        assert close_order.side == OrderSide.SELL  # long position → sell to close
        assert close_order.asset_class == AssetClass.OPTION
        assert float(close_order.quantity) == 10.0

        # Event published
        assert len(received) == 1
        assert received[0][1]["dte"] == 1

        # Position removed from tracking
        assert len(manager._positions) == 0

    @pytest.mark.asyncio
    async def test_auto_close_short_position(self, manager, bus, exec_adapter):
        """Short position triggers BUY to close."""
        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19), quantity=-5.0)
        manager.set_positions([pos])
        await manager.check_expirations(today=today)

        close_order = exec_adapter.submit_order.call_args[0][0]
        assert close_order.side == OrderSide.BUY
        assert float(close_order.quantity) == 5.0

    @pytest.mark.asyncio
    async def test_auto_close_at_zero_dte(self, manager, exec_adapter):
        """Position expiring today (DTE=0) triggers auto-close."""
        today = date(2024, 1, 19)
        pos = _pos(expiration=date(2024, 1, 19))  # DTE = 0
        manager.set_positions([pos])
        await manager.check_expirations(today=today)

        exec_adapter.submit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_close_removes_from_alerted(self, manager, bus):
        """After auto-close, symbol is removed from alerted set."""
        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19))
        manager.set_positions([pos])
        manager._alerted.add(pos.symbol)
        await manager.check_expirations(today=today)
        assert pos.symbol not in manager._alerted

    @pytest.mark.asyncio
    async def test_auto_close_failure_keeps_position(self, manager, exec_adapter):
        """If submit_order fails, position is NOT removed."""
        exec_adapter.submit_order = AsyncMock(side_effect=RuntimeError("API error"))
        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19))
        manager.set_positions([pos])
        await manager.check_expirations(today=today)
        assert len(manager._positions) == 1  # still tracked


# ── ExpirationManager — rolling ────────────────────────────────────────


class TestRolling:
    @pytest.mark.asyncio
    async def test_roll_when_enabled(self, bus, exec_adapter):
        """When roll_enabled=True, a new order is submitted after close."""
        config = ExpirationConfig(
            auto_close_dte=1,
            alert_dte=7,
            roll_enabled=True,
            roll_target_dte=30,
        )
        mgr = ExpirationManager(config=config, event_bus=bus, exec_adapter=exec_adapter)

        received = []

        async def handler(ch, ev):
            received.append((ch, ev))

        await bus.subscribe(POSITION_ROLLED, handler)

        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19), quantity=10.0)
        mgr.set_positions([pos])
        await mgr.check_expirations(today=today)

        # Two orders: close + roll
        assert exec_adapter.submit_order.call_count == 2
        roll_order = exec_adapter.submit_order.call_args_list[1][0][0]
        assert roll_order.side == OrderSide.BUY  # long → buy to re-enter
        assert roll_order.expiration_date == date(2024, 1, 19) + timedelta(days=30)

        # Roll event published
        assert len(received) == 1
        assert received[0][1]["roll_target_dte"] == 30

    @pytest.mark.asyncio
    async def test_no_roll_when_disabled(self, manager, exec_adapter):
        """Default roll_enabled=False means no roll after close."""
        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19))
        manager.set_positions([pos])
        await manager.check_expirations(today=today)

        # Only one call: the close order
        assert exec_adapter.submit_order.call_count == 1

    @pytest.mark.asyncio
    async def test_roll_failure_does_not_crash(self, bus, exec_adapter):
        """If the roll order fails, the manager doesn't raise."""
        config = ExpirationConfig(
            auto_close_dte=1, alert_dte=7, roll_enabled=True, roll_target_dte=30
        )
        # First call (close) succeeds, second call (roll) fails
        exec_adapter.submit_order = AsyncMock(
            side_effect=[None, RuntimeError("roll failed")]
        )
        mgr = ExpirationManager(config=config, event_bus=bus, exec_adapter=exec_adapter)

        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19))
        mgr.set_positions([pos])
        await mgr.check_expirations(today=today)  # should not raise


# ── ExpirationManager — no exec_adapter ────────────────────────────────


class TestNoExecAdapter:
    @pytest.mark.asyncio
    async def test_auto_close_without_adapter(self, bus):
        """Auto-close still publishes event even without an exec adapter."""
        config = ExpirationConfig(auto_close_dte=1, alert_dte=7)
        mgr = ExpirationManager(config=config, event_bus=bus, exec_adapter=None)

        received = []

        async def handler(ch, ev):
            received.append(ev)

        await bus.subscribe(POSITION_AUTO_CLOSED, handler)

        today = date(2024, 1, 18)
        pos = _pos(expiration=date(2024, 1, 19))
        mgr.set_positions([pos])
        await mgr.check_expirations(today=today)

        assert len(received) == 1


# ── ExpirationManager — lifecycle (start / stop) ──────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self, manager, bus):
        """Start creates a check task, stop cancels it."""
        await manager.start()
        assert manager._check_task is not None
        assert not manager._check_task.done()

        await manager.stop()
        assert manager._check_task.done()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, manager):
        """Stopping without starting doesn't raise."""
        await manager.stop()  # no-op


# ── ExpirationManager — mixed scenario ────────────────────────────────


class TestMixedScenario:
    @pytest.mark.asyncio
    async def test_multiple_positions_different_actions(self, manager, bus, exec_adapter):
        """One position gets auto-closed, another gets alerted, a third is fine."""
        close_events = []
        alert_events = []

        async def close_handler(ch, ev):
            close_events.append(ev)

        async def alert_handler(ch, ev):
            alert_events.append(ev)

        await bus.subscribe(POSITION_AUTO_CLOSED, close_handler)
        await bus.subscribe(EXPIRATION_WARNING, alert_handler)

        today = date(2024, 1, 18)
        pos_close = _pos(symbol="CLOSE", expiration=date(2024, 1, 19))  # DTE=1
        pos_alert = _pos(symbol="ALERT", expiration=date(2024, 1, 22))  # DTE=4
        pos_safe = _pos(symbol="SAFE", expiration=date(2024, 3, 15))    # DTE=56

        manager.set_positions([pos_close, pos_alert, pos_safe])
        await manager.check_expirations(today=today)

        assert len(close_events) == 1
        assert close_events[0]["symbol"] == "CLOSE"
        assert len(alert_events) == 1
        assert alert_events[0]["symbol"] == "ALERT"

        # CLOSE removed, ALERT and SAFE remain
        remaining = [p.symbol for p in manager._positions]
        assert "CLOSE" not in remaining
        assert "ALERT" in remaining
        assert "SAFE" in remaining
