"""Expiration management — monitors DTE and auto-closes / rolls positions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from trading_platform.core.enums import AssetClass, ContractType, OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Order, Position


# Event channel constants
EXPIRATION_WARNING = "options.expiration.warning"
POSITION_AUTO_CLOSED = "options.position.auto_closed"
POSITION_ROLLED = "options.position.rolled"


@dataclass
class ExpirationConfig:
    """Configuration for expiration management."""

    auto_close_dte: int = 1
    alert_dte: int = 7
    roll_enabled: bool = False
    roll_target_dte: int = 30
    check_interval_seconds: float = 60.0


@dataclass
class OptionsPosition:
    """Lightweight options position with expiration info."""

    symbol: str
    underlying: str
    quantity: float
    contract_type: ContractType
    strike_price: float
    expiration_date: date
    strategy_type: str = ""  # non-empty for multi-leg positions


class ExpirationManager:
    """Monitors DTE for open options positions and takes action.

    Actions:
    - Alert when position reaches ``alert_dte``
    - Auto-close when position reaches ``auto_close_dte``
    - Optionally roll to a new expiration when auto-closing
    """

    def __init__(
        self,
        config: ExpirationConfig,
        event_bus: EventBus,
        exec_adapter: Any | None = None,
        strategy_builder: Any | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._exec_adapter = exec_adapter
        self._strategy_builder = strategy_builder
        self._log = get_logger("options.expiration")
        self._positions: list[OptionsPosition] = []
        self._alerted: set[str] = set()  # symbols that already received alert
        self._check_task: asyncio.Task[None] | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start periodic DTE checking and subscribe to position updates."""
        await self._bus.subscribe(
            "execution.portfolio.update", self._on_portfolio_update
        )
        self._check_task = asyncio.create_task(self._check_loop())
        self._log.info(
            "expiration manager started",
            auto_close_dte=self._config.auto_close_dte,
            alert_dte=self._config.alert_dte,
            roll_enabled=self._config.roll_enabled,
        )

    async def stop(self) -> None:
        """Stop the check loop."""
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        await self._bus.unsubscribe(
            "execution.portfolio.update", self._on_portfolio_update
        )
        self._log.info("expiration manager stopped")

    # ── Position tracking ─────────────────────────────────────────────

    def set_positions(self, positions: list[OptionsPosition]) -> None:
        """Directly set the monitored options positions."""
        self._positions = list(positions)

    async def _on_portfolio_update(self, channel: str, event: Any) -> None:
        """Handle portfolio update events to refresh our positions list."""
        if not isinstance(event, dict):
            return
        if event.get("asset_class") != "option":
            return
        # We keep our existing positions — callers can push via set_positions
        # or ExpirationManager can parse portfolio updates when expiration data
        # is available.

    # ── Core logic ────────────────────────────────────────────────────

    async def check_expirations(self, today: date | None = None) -> None:
        """Check all positions against DTE thresholds.

        Uses *today* for the current date (defaults to ``date.today()``).
        """
        today = today or date.today()
        for pos in list(self._positions):
            dte = (pos.expiration_date - today).days

            if dte <= self._config.auto_close_dte:
                await self._auto_close(pos, dte)
            elif dte <= self._config.alert_dte and pos.symbol not in self._alerted:
                await self._alert(pos, dte)

    async def _alert(self, pos: OptionsPosition, dte: int) -> None:
        """Emit an expiration warning event."""
        self._alerted.add(pos.symbol)
        await self._bus.publish(
            EXPIRATION_WARNING,
            {
                "symbol": pos.symbol,
                "underlying": pos.underlying,
                "expiration_date": pos.expiration_date.isoformat(),
                "dte": dte,
                "quantity": pos.quantity,
            },
        )
        self._log.warning(
            "expiration warning",
            symbol=pos.symbol,
            dte=dte,
        )

    async def _auto_close(self, pos: OptionsPosition, dte: int) -> None:
        """Close the position and optionally roll it."""
        # Submit closing order
        close_order = Order(
            symbol=pos.symbol,
            side=OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=abs(pos.quantity),
            asset_class=AssetClass.OPTION,
            contract_type=pos.contract_type,
            strike_price=pos.strike_price,
            expiration_date=pos.expiration_date,
            underlying_symbol=pos.underlying,
            option_symbol=pos.symbol,
        )

        if self._exec_adapter:
            try:
                await self._exec_adapter.submit_order(close_order)
            except Exception as exc:
                self._log.error(
                    "failed to auto-close position",
                    symbol=pos.symbol,
                    error=str(exc),
                )
                return

        await self._bus.publish(
            POSITION_AUTO_CLOSED,
            {
                "symbol": pos.symbol,
                "underlying": pos.underlying,
                "expiration_date": pos.expiration_date.isoformat(),
                "dte": dte,
                "quantity": pos.quantity,
            },
        )
        self._log.info("position auto-closed", symbol=pos.symbol, dte=dte)

        # Remove from tracked positions
        self._positions = [p for p in self._positions if p.symbol != pos.symbol]
        self._alerted.discard(pos.symbol)

        # Roll if enabled
        if self._config.roll_enabled:
            await self._roll_position(pos)

    async def _roll_position(self, pos: OptionsPosition) -> None:
        """Roll the closed position to a new expiration."""
        new_expiration = pos.expiration_date + timedelta(
            days=self._config.roll_target_dte
        )

        new_order = Order(
            symbol=pos.symbol,  # symbol will be updated by adapter
            side=OrderSide.BUY if pos.quantity > 0 else OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=abs(pos.quantity),
            asset_class=AssetClass.OPTION,
            contract_type=pos.contract_type,
            strike_price=pos.strike_price,
            expiration_date=new_expiration,
            underlying_symbol=pos.underlying,
            option_symbol="",  # will be determined by adapter / chain lookup
        )

        if self._exec_adapter:
            try:
                await self._exec_adapter.submit_order(new_order)
            except Exception as exc:
                self._log.error(
                    "failed to roll position",
                    symbol=pos.symbol,
                    error=str(exc),
                )
                return

        await self._bus.publish(
            POSITION_ROLLED,
            {
                "old_symbol": pos.symbol,
                "underlying": pos.underlying,
                "old_expiration": pos.expiration_date.isoformat(),
                "new_expiration": new_expiration.isoformat(),
                "quantity": pos.quantity,
                "roll_target_dte": self._config.roll_target_dte,
            },
        )
        self._log.info(
            "position rolled",
            symbol=pos.symbol,
            new_expiration=new_expiration.isoformat(),
        )

    # ── Background loop ──────────────────────────────────────────────

    async def _check_loop(self) -> None:
        """Periodically check expirations."""
        while True:
            try:
                await asyncio.sleep(self._config.check_interval_seconds)
                await self.check_expirations()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.warning(
                    "expiration check error", error=str(exc)
                )
