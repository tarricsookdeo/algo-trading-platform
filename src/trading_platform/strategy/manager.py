"""StrategyManager orchestrates strategy registration, lifecycle, and event wiring."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Bar, Order, Position, QuoteTick, TradeTick
from trading_platform.strategy.base import Strategy
from trading_platform.strategy.context import StrategyContext


class StrategyState(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class StrategyEntry:
    """Internal record for a registered strategy."""

    def __init__(self, strategy: Strategy, context: StrategyContext) -> None:
        self.strategy = strategy
        self.context = context
        self.state = StrategyState.REGISTERED
        self.trades_executed: int = 0
        self.wins: int = 0
        self.losses: int = 0
        self.pnl: float = 0.0
        self.signals: list[dict[str, Any]] = []


class StrategyManager:
    """Manages the lifecycle of trading strategies."""

    def __init__(
        self,
        event_bus: EventBus,
        exec_adapter: Any = None,
        risk_manager: Any = None,
        bracket_manager: Any = None,
        options_strategy_builder: Any = None,
    ) -> None:
        self._bus = event_bus
        self._exec = exec_adapter
        self._risk = risk_manager
        self._bracket = bracket_manager
        self._options_builder = options_strategy_builder
        self._log = get_logger("strategy.manager")
        self._strategies: dict[str, StrategyEntry] = {}

    def register(self, strategy: Strategy) -> None:
        """Register a strategy for management."""
        sid = strategy.name
        if sid in self._strategies:
            self._log.warning("strategy already registered", strategy=sid)
            return
        context = StrategyContext(
            strategy_id=sid,
            event_bus=self._bus,
            exec_adapter=self._exec,
            risk_manager=self._risk,
            bracket_manager=self._bracket,
            options_strategy_builder=self._options_builder,
        )
        strategy.context = context
        strategy.event_bus = self._bus
        entry = StrategyEntry(strategy, context)
        self._strategies[sid] = entry
        self._log.info("strategy registered", strategy=sid)

    def deregister(self, strategy_id: str) -> None:
        """Remove a strategy."""
        self._strategies.pop(strategy_id, None)

    async def start_strategy(self, strategy_id: str) -> None:
        """Start a single strategy and wire event subscriptions."""
        entry = self._strategies.get(strategy_id)
        if not entry:
            self._log.warning("strategy not found", strategy=strategy_id)
            return
        if entry.state == StrategyState.ACTIVE:
            return

        try:
            strategy = entry.strategy
            strategy.is_active = True
            await strategy.on_start()
            entry.state = StrategyState.ACTIVE

            await self._bus.publish("strategy.lifecycle", {
                "strategy_id": strategy_id,
                "state": str(entry.state),
                "action": "started",
            })
            self._log.info("strategy started", strategy=strategy_id)
        except Exception as exc:
            entry.state = StrategyState.ERROR
            self._log.error("strategy start failed", strategy=strategy_id, error=str(exc))

    async def stop_strategy(self, strategy_id: str) -> None:
        """Stop a single strategy."""
        entry = self._strategies.get(strategy_id)
        if not entry:
            return
        if entry.state not in (StrategyState.ACTIVE, StrategyState.PAUSED):
            return

        try:
            entry.strategy.is_active = False
            await entry.strategy.on_stop()
            entry.state = StrategyState.STOPPED

            await self._bus.publish("strategy.lifecycle", {
                "strategy_id": strategy_id,
                "state": str(entry.state),
                "action": "stopped",
            })
            self._log.info("strategy stopped", strategy=strategy_id)
        except Exception as exc:
            entry.state = StrategyState.ERROR
            self._log.error("strategy stop failed", strategy=strategy_id, error=str(exc))

    async def start_all(self) -> None:
        for sid in list(self._strategies):
            await self.start_strategy(sid)

    async def stop_all(self) -> None:
        for sid in list(self._strategies):
            await self.stop_strategy(sid)

    async def dispatch_quote(self, channel: str, event: Any) -> None:
        """EventBus callback for quote events."""
        if not isinstance(event, QuoteTick) and not (isinstance(event, dict) and "symbol" in event):
            return
        quote = event if isinstance(event, QuoteTick) else QuoteTick(**event)
        for entry in self._strategies.values():
            if entry.state == StrategyState.ACTIVE:
                entry.context.update_quote(quote)
                try:
                    await entry.strategy.on_quote(quote)
                except Exception as exc:
                    self._log.warning("strategy on_quote error", strategy=entry.strategy.name, error=str(exc))

    async def dispatch_trade(self, channel: str, event: Any) -> None:
        """EventBus callback for trade events."""
        if not isinstance(event, TradeTick) and not (isinstance(event, dict) and "symbol" in event):
            return
        trade = event if isinstance(event, TradeTick) else TradeTick(**event)
        for entry in self._strategies.values():
            if entry.state == StrategyState.ACTIVE:
                try:
                    await entry.strategy.on_trade(trade)
                except Exception as exc:
                    self._log.warning("strategy on_trade error", strategy=entry.strategy.name, error=str(exc))

    async def dispatch_bar(self, channel: str, event: Any) -> None:
        """EventBus callback for bar events."""
        if not isinstance(event, Bar) and not (isinstance(event, dict) and "symbol" in event):
            return
        bar = event if isinstance(event, Bar) else Bar(**event)
        for entry in self._strategies.values():
            if entry.state == StrategyState.ACTIVE:
                entry.context.update_bar(bar)
                try:
                    await entry.strategy.on_bar(bar)
                except Exception as exc:
                    self._log.warning("strategy on_bar error", strategy=entry.strategy.name, error=str(exc))

    async def dispatch_order_update(self, channel: str, event: Any) -> None:
        """EventBus callback for order update events."""
        for entry in self._strategies.values():
            if entry.state == StrategyState.ACTIVE and hasattr(entry.strategy, "on_order_update"):
                try:
                    await entry.strategy.on_order_update(event)
                except Exception:
                    pass

    async def dispatch_position_update(self, channel: str, event: Any) -> None:
        """EventBus callback for position update events."""
        positions = event.get("positions", []) if isinstance(event, dict) else []
        platform_positions = []
        for p in positions:
            if isinstance(p, Position):
                platform_positions.append(p)
            elif isinstance(p, dict):
                platform_positions.append(Position(**p))

        for entry in self._strategies.values():
            entry.context.update_positions(platform_positions)
            if entry.state == StrategyState.ACTIVE and hasattr(entry.strategy, "on_position_update"):
                try:
                    await entry.strategy.on_position_update(platform_positions)
                except Exception:
                    pass

    async def wire_events(self) -> None:
        """Subscribe to EventBus channels to dispatch to strategies."""
        await self._bus.subscribe(Channel.QUOTE, self.dispatch_quote)
        await self._bus.subscribe(Channel.TRADE, self.dispatch_trade)
        await self._bus.subscribe(Channel.BAR, self.dispatch_bar)
        await self._bus.subscribe(Channel.ORDER, self.dispatch_order_update)
        await self._bus.subscribe("execution.portfolio.update", self.dispatch_position_update)

    async def unwire_events(self) -> None:
        await self._bus.unsubscribe(Channel.QUOTE, self.dispatch_quote)
        await self._bus.unsubscribe(Channel.TRADE, self.dispatch_trade)
        await self._bus.unsubscribe(Channel.BAR, self.dispatch_bar)
        await self._bus.unsubscribe(Channel.ORDER, self.dispatch_order_update)
        await self._bus.unsubscribe("execution.portfolio.update", self.dispatch_position_update)

    def get_strategy_info(self) -> list[dict[str, Any]]:
        """Return info about all registered strategies."""
        result = []
        for sid, entry in self._strategies.items():
            win_rate = 0.0
            total = entry.wins + entry.losses
            if total > 0:
                win_rate = entry.wins / total
            result.append({
                "strategy_id": sid,
                "state": str(entry.state),
                "trades_executed": entry.trades_executed,
                "win_rate": round(win_rate, 4),
                "pnl": round(entry.pnl, 2),
                "signals": len(entry.signals),
            })
        return result

    def get_strategy_entry(self, strategy_id: str) -> StrategyEntry | None:
        return self._strategies.get(strategy_id)
