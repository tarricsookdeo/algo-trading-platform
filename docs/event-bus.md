# Event Bus Reference

## Overview

The `EventBus` is the central messaging system of the platform. All components communicate through named channels using an async publish/subscribe pattern. There is no direct coupling between publishers and subscribers.

## EventBus API

`trading_platform.core.events.EventBus`

### Creating an EventBus

```python
from trading_platform.core.events import EventBus

bus = EventBus()
```

### Publishing Events

```python
from trading_platform.core.enums import Channel

# Using a Channel enum
await bus.publish(Channel.QUOTE, quote_tick)

# Using a string channel
await bus.publish("strategy.signal", {"strategy_id": "my-strat", "signal": {...}})
```

All subscribers on the channel (and wildcard subscribers) are called concurrently via `asyncio.gather`.

### Subscribing

```python
async def on_quote(channel: str, event: Any) -> None:
    print(f"Got quote on {channel}: {event}")

await bus.subscribe(Channel.QUOTE, on_quote)
```

The callback signature is:

```python
Callback = Callable[[str, Any], Coroutine[Any, Any, None]]
```

- First argument: the channel name (string)
- Second argument: the event payload (any type)

### Unsubscribing

```python
await bus.unsubscribe(Channel.QUOTE, on_quote)
```

### Wildcard Subscriptions

Subscribe to `"*"` to receive all events on all channels:

```python
async def on_any(channel: str, event: Any) -> None:
    print(f"[{channel}] {event}")

await bus.subscribe("*", on_any)
```

Wildcard subscribers receive events from every channel. The `"*"` channel itself does not trigger wildcard subscribers (no infinite loop).

### Metrics

```python
# Total events published since startup
bus.total_published  # int

# Per-channel counts
bus.channel_counts  # dict[str, int]

# Rolling events per second (5-second window)
rate = bus.events_per_second()  # float

# Total active subscriptions
count = bus.subscriber_count  # int
```

## Event Channels

### Market Data Channels

| Channel | Enum | Payload Type | Publisher |
|---------|------|-------------|-----------|
| `quote` | `Channel.QUOTE` | `QuoteTick` | `AlpacaDataAdapter` |
| `trade` | `Channel.TRADE` | `TradeTick` | `AlpacaDataAdapter` |
| `bar` | `Channel.BAR` | `Bar` | `AlpacaDataAdapter` |
| `status` | `Channel.STATUS` | `TradingStatus` or `LULD` | `AlpacaDataAdapter` |
| `error` | `Channel.ERROR` | `dict` | Various |

#### `QuoteTick` Payload

```python
{
    "symbol": "AAPL",
    "bid_price": 150.25,
    "bid_size": 200.0,
    "ask_price": 150.30,
    "ask_size": 100.0,
    "bid_exchange": "Q",
    "ask_exchange": "Q",
    "timestamp": "2026-03-12T14:30:00Z",
    "conditions": []
}
```

#### `TradeTick` Payload

```python
{
    "symbol": "AAPL",
    "price": 150.27,
    "size": 50.0,
    "exchange": "Q",
    "trade_id": "123456",
    "conditions": ["@"],
    "timestamp": "2026-03-12T14:30:00Z",
    "tape": "C"
}
```

#### `Bar` Payload

```python
{
    "symbol": "AAPL",
    "open": 150.00,
    "high": 150.50,
    "low": 149.80,
    "close": 150.25,
    "volume": 15000.0,
    "vwap": 150.15,
    "trade_count": 200,
    "timestamp": "2026-03-12T14:30:00Z",
    "bar_type": "minute"
}
```

### Execution Channels

| Channel | Payload | Description |
|---------|---------|-------------|
| `execution.order.submitted` | `{order_id, symbol, side, order_type, quantity}` | Order accepted by broker API |
| `execution.order.filled` | `{order_id, status}` | Order fully filled |
| `execution.order.partially_filled` | `{order_id, status}` | Partial fill received |
| `execution.order.cancelled` | `{order_id, status?}` | Order cancelled |
| `execution.order.rejected` | `{order_id, status}` | Order rejected by broker |
| `execution.order.error` | `{order_id, error, detail}` | API error, rate limit, or cancel failure |
| `execution.portfolio.update` | `{positions: [...], account: {...}}` | Portfolio sync completed |
| `execution.account.update` | `{buying_power_cash, buying_power_margin, equity}` or `{status}` | Account info update |

#### Order Submitted Payload

```python
{
    "order_id": "abc-123",
    "symbol": "AAPL",
    "side": "buy",
    "order_type": "limit",
    "quantity": 10.0
}
```

#### Multi-leg Order Submitted Payload

```python
{
    "order_id": "spread-001",
    "type": "multileg",
    "legs": 2
}
```

#### Portfolio Update Payload

```python
{
    "positions": [
        {
            "symbol": "AAPL",
            "quantity": 100.0,
            "avg_entry_price": 150.25,
            "market_value": 15200.0,
            "unrealized_pnl": 175.0,
            "side": ""
        }
    ],
    "account": {
        "buying_power_cash": 50000.0,
        "buying_power_margin": 100000.0,
        "equity": 150000.0
    }
}
```

### Strategy Channels

| Channel | Payload | Description |
|---------|---------|-------------|
| `strategy.signal` | `{strategy_id, signal: {symbol, side, reason}}` | Strategy generated a trading signal |
| `strategy.lifecycle` | `{strategy_id, state, ...}` | Strategy state change (started, stopped, etc.) |

#### Signal Payload

```python
{
    "strategy_id": "sma-crossover",
    "signal": {
        "symbol": "AAPL",
        "side": "buy",
        "reason": "SMA crossover: short=152.30 > long=150.10"
    }
}
```

### Risk Channels

| Channel | Payload | Description |
|---------|---------|-------------|
| `risk.check.passed` | `{strategy_id, order_id}` | Pre-trade check passed |
| `risk.check.failed` | `{order_id, reason}` | Pre-trade check failed |
| `risk.alert` | `{type, message, ...}` | Non-halting risk alert (e.g., trade count exceeded) |
| `risk.halt` | `{reason}` | Trading halted — all new orders will be rejected |

#### Risk Alert Payload

```python
{
    "type": "daily_trade_count",
    "message": "Daily trade count 105 exceeds limit 100",
    "trade_count": 105
}
```

### System Channels

| Channel | Enum | Payload | Description |
|---------|------|---------|-------------|
| `system` | `Channel.SYSTEM` | `SystemEvent` or `dict` | System-level events |

#### SystemEvent Payload

```python
{
    "component": "platform",
    "message": "dashboard running on http://0.0.0.0:8080",
    "level": "info",
    "data": {},
    "timestamp": "2026-03-12T14:30:00Z"
}
```

## Patterns for Using the Event Bus

### Listening to All Market Data

```python
async def on_market_data(channel: str, event: Any) -> None:
    if channel == "quote":
        handle_quote(event)
    elif channel == "trade":
        handle_trade(event)
    elif channel == "bar":
        handle_bar(event)

await bus.subscribe(Channel.QUOTE, on_market_data)
await bus.subscribe(Channel.TRADE, on_market_data)
await bus.subscribe(Channel.BAR, on_market_data)
```

### Monitoring All Execution Events

```python
async def on_execution(channel: str, event: Any) -> None:
    print(f"Execution event [{channel}]: {event}")

for ch in [
    "execution.order.submitted",
    "execution.order.filled",
    "execution.order.cancelled",
    "execution.order.rejected",
    "execution.order.error",
]:
    await bus.subscribe(ch, on_execution)
```

### Global Event Logger

```python
async def log_all(channel: str, event: Any) -> None:
    print(f"[{channel}] {event}")

await bus.subscribe("*", log_all)
```

### Publishing Custom Events

```python
await bus.publish("custom.my_component.event", {
    "key": "value",
    "timestamp": datetime.now(UTC).isoformat(),
})
```

Custom channels work just like built-in ones — any string can be a channel name.
