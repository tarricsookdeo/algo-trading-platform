# Strategy Development Guide

## Overview

The strategy framework provides an abstract base class with lifecycle management, market data callbacks, and an execution context. Strategies receive real-time market data through the EventBus and submit orders through a `StrategyContext` that handles risk validation and execution.

## Strategy Base Class

`trading_platform.strategy.base.Strategy`

Every strategy extends the `Strategy` ABC and implements three required callbacks:

```python
from trading_platform.strategy.base import Strategy
from trading_platform.core.events import EventBus
from trading_platform.core.models import QuoteTick, TradeTick, Bar

class MyStrategy(Strategy):
    def __init__(self, name: str, event_bus: EventBus, config: dict | None = None) -> None:
        super().__init__(name, event_bus, config)

    async def on_quote(self, quote: QuoteTick) -> None:
        """Called on every quote update."""
        ...

    async def on_trade(self, trade: TradeTick) -> None:
        """Called on every trade update."""
        ...

    async def on_bar(self, bar: Bar) -> None:
        """Called on every bar update."""
        ...
```

### Lifecycle Hooks

| Method | Required | Description |
|--------|----------|-------------|
| `on_start()` | No | Called when the strategy is started. Use for setup/initialization. |
| `on_stop()` | No | Called when the strategy is stopped. Use for cleanup. |
| `on_quote(quote)` | Yes | Called on every quote update |
| `on_trade(trade)` | Yes | Called on every trade update |
| `on_bar(bar)` | Yes | Called on every bar update (typically 1-minute bars) |
| `on_order_update(update)` | No | Called when an order status changes |
| `on_position_update(positions)` | No | Called when positions are updated |
| `on_signal(signal)` | No | Called when the strategy generates a signal |

### Strategy Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Strategy identifier |
| `event_bus` | `EventBus` | Reference to the platform event bus |
| `config` | `dict` | Strategy-specific configuration |
| `context` | `StrategyContext` | Injected by StrategyManager — provides market data and execution |
| `is_active` | `bool` | Whether the strategy is currently running |

## StrategyContext API

`trading_platform.strategy.context.StrategyContext`

The context is injected into each strategy by the StrategyManager. It provides access to market data, execution, and risk validation without strategies needing direct adapter references.

### Market Data Access

```python
# Get the latest quote for a symbol
quote = self.context.get_latest_quote("AAPL")
if quote:
    print(f"AAPL bid={quote.bid_price} ask={quote.ask_price}")

# Get the latest bar for a symbol
bar = self.context.get_latest_bar("AAPL")
if bar:
    print(f"AAPL close={bar.close} volume={bar.volume}")

# Get current positions
positions = self.context.get_positions()
for pos in positions:
    print(f"{pos.symbol}: qty={pos.quantity} pnl={pos.unrealized_pnl}")
```

### Order Submission

Orders go through risk checks before execution:

```python
from trading_platform.core.models import Order
from trading_platform.core.enums import OrderSide, OrderType

# Market order
order = Order(
    symbol="AAPL",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    quantity=10.0,
)
result = await self.context.submit_order(order)

# result is None if risk check failed, otherwise the SDK order object
```

```python
# Limit order
order = Order(
    symbol="AAPL",
    side=OrderSide.SELL,
    order_type=OrderType.LIMIT,
    quantity=10.0,
    limit_price=155.00,
)
result = await self.context.submit_order(order)
```

```python
# Cancel an order
await self.context.cancel_order("order-id-123")
```

### Order Flow

```
context.submit_order(order)
    │
    ├── RiskManager.pre_trade_check(order, positions)
    │       ├── PASS → publish("risk.check.passed") → ExecAdapter.submit_order()
    │       └── FAIL → publish("risk.check.failed") → return None
    │
    └── Returns SDK order object or None
```

## StrategyManager

`trading_platform.strategy.manager.StrategyManager`

The manager handles registration, lifecycle, and event dispatch for all strategies.

### Registration and Control

```python
from trading_platform.strategy.manager import StrategyManager
from trading_platform.core.events import EventBus

bus = EventBus()
manager = StrategyManager(event_bus=bus, exec_adapter=exec_adapter, risk_manager=risk_manager)

# Register a strategy
strategy = MyStrategy("my-strategy", bus, config={"symbols": ["AAPL"]})
manager.register(strategy)

# Start
await manager.start_strategy("my-strategy")

# Stop
await manager.stop_strategy("my-strategy")

# Start/stop all
await manager.start_all()
await manager.stop_all()

# Deregister
manager.deregister("my-strategy")
```

### Event Wiring

The manager subscribes to market data channels and dispatches events to active strategies:

```python
await manager.wire_events()    # Subscribe to quote, trade, bar, order, position channels
await manager.unwire_events()  # Unsubscribe from all channels
```

Dispatch methods:

| Method | Source Channel | Strategy Callback |
|--------|---------------|-------------------|
| `dispatch_quote` | `Channel.QUOTE` | `strategy.on_quote(quote)` |
| `dispatch_trade` | `Channel.TRADE` | `strategy.on_trade(trade)` |
| `dispatch_bar` | `Channel.BAR` | `strategy.on_bar(bar)` |
| `dispatch_order_update` | `Channel.ORDER` | `strategy.on_order_update(update)` |
| `dispatch_position_update` | `Channel.POSITION` | `strategy.on_position_update(positions)` |

### Strategy State

```python
class StrategyState(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"
```

### Strategy Lifecycle

```
register()          start_strategy()         stop_strategy()
    │                     │                       │
    ▼                     ▼                       ▼
REGISTERED ─────────► ACTIVE ──────────────► STOPPED
                         │                       ▲
                         └── error ──► ERROR ────┘
```

### Querying Strategy Info

```python
# Get info for all strategies
infos = manager.get_strategy_info()
# Returns list of dicts with: strategy_id, state, trades_executed, wins, losses, pnl, signals

# Get a specific strategy entry
entry = manager.get_strategy_entry("my-strategy")
# entry.state, entry.trades_executed, entry.pnl, etc.
```

## Writing Your First Strategy

### Step 1: Create the Strategy File

Create `src/trading_platform/strategy/examples/mean_reversion.py`:

```python
"""Mean reversion strategy example."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Bar, Order, QuoteTick, TradeTick
from trading_platform.strategy.base import Strategy


class MeanReversionStrategy(Strategy):
    """Buys when price is 2 std devs below mean, sells when 2 above."""

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, event_bus, config)
        self.window: int = self.config.get("window", 20)
        self.z_threshold: float = self.config.get("z_threshold", 2.0)
        self.symbols: list[str] = self.config.get("symbols", [])
        self.quantity: float = self.config.get("quantity", 10.0)
        self._prices: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )
        self._log = get_logger(f"strategy.{name}")

    async def on_start(self) -> None:
        self._prices.clear()
        self._log.info("mean reversion strategy started", symbols=self.symbols)

    async def on_stop(self) -> None:
        self._log.info("mean reversion strategy stopped")

    async def on_quote(self, quote: QuoteTick) -> None:
        pass  # This strategy uses bars, not quotes

    async def on_trade(self, trade: TradeTick) -> None:
        pass  # This strategy uses bars, not trades

    async def on_bar(self, bar: Bar) -> None:
        if self.symbols and bar.symbol not in self.symbols:
            return

        self._prices[bar.symbol].append(bar.close)
        prices = list(self._prices[bar.symbol])

        if len(prices) < self.window:
            return

        mean = sum(prices) / len(prices)
        std = (sum((p - mean) ** 2 for p in prices) / len(prices)) ** 0.5
        if std == 0:
            return

        z_score = (bar.close - mean) / std

        if z_score < -self.z_threshold:
            await self._submit(bar.symbol, OrderSide.BUY, f"z={z_score:.2f}")
        elif z_score > self.z_threshold:
            await self._submit(bar.symbol, OrderSide.SELL, f"z={z_score:.2f}")

    async def _submit(self, symbol: str, side: OrderSide, reason: str) -> None:
        if not self.context:
            return

        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=self.quantity,
        )

        await self.event_bus.publish("strategy.signal", {
            "strategy_id": self.name,
            "signal": {"symbol": symbol, "side": str(side), "reason": reason},
        })

        await self.context.submit_order(order)
```

### Step 2: Register with the Platform

In your startup code (or modify `main.py`):

```python
from trading_platform.strategy.examples.mean_reversion import MeanReversionStrategy

strategy = MeanReversionStrategy(
    name="mean-reversion-aapl",
    event_bus=event_bus,
    config={
        "symbols": ["AAPL"],
        "window": 20,
        "z_threshold": 2.0,
        "quantity": 10.0,
    },
)
strategy_manager.register(strategy)
await strategy_manager.start_strategy("mean-reversion-aapl")
```

## SMA Crossover Example Walkthrough

The built-in `SMACrossoverStrategy` (`strategy/examples/sma_crossover.py`) demonstrates the standard pattern:

1. **Configuration** — `short_window` (10), `long_window` (30), `symbols`, `quantity`
2. **State** — Price deque per symbol, position side tracking
3. **Signal generation** — Computes short/long SMA on each bar, detects crossovers
4. **Order submission** — Creates market orders via `self.context.submit_order()`
5. **Event publishing** — Publishes signals to `strategy.signal` channel

Key code flow in `on_bar()`:

```python
# Accumulate prices
self._prices[bar.symbol].append(bar.close)

# Wait for enough data
if len(prices) < self.long_window:
    return

# Compute SMAs
short_sma = sum(prices[-self.short_window:]) / self.short_window
long_sma = sum(prices[-self.long_window:]) / self.long_window

# Generate signal on crossover
if short_sma > long_sma and current_side != "long":
    signal = {"symbol": bar.symbol, "side": "buy", "reason": "..."}
    await self.on_signal(signal)
```

## Tips for Strategy Development

- **Filter symbols** — Always check `bar.symbol` / `quote.symbol` against your target symbols
- **Buffer data** — Use `collections.deque(maxlen=N)` for rolling windows
- **Avoid blocking** — All callbacks are `async` — never use `time.sleep()`
- **Log decisions** — Use `get_logger()` to trace signals and order submissions
- **Handle missing context** — Always check `if self.context:` before submitting orders
- **Publish signals** — Use `self.event_bus.publish("strategy.signal", {...})` so the dashboard can display them
- **Test offline** — Unit test with mock EventBus and StrategyContext before live deployment
