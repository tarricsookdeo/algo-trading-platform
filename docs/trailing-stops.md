# Trailing Stops

## Overview

The `TrailingStopManager` implements dynamic trailing stop-loss orders. As the price rises, the stop level ratchets up (but never down). When the price drops to the stop level, the resting stop order executes.

## How It Works

1. You create a trailing stop with a symbol, quantity, and trail amount (absolute $) or trail percent
2. The manager places an initial stop order at `current_price - trail_amount`
3. As quotes arrive and the bid price rises, the manager updates `highest_price` and computes a new stop level
4. If the new stop level is higher than the current stop, the manager uses `cancel_and_replace` to update the resting stop order
5. The stop level never decreases — it only ratchets up
6. When the stop order fills (price drops to stop level), the trailing stop completes

```
Price ──────────────────────────────────────────────────
                        /\         /\
                       /  \       /  \
                      /    \     /    \____ ← highest
                     /      \   /          \
                    /        \ /            \ ← stop hit
Stop  ─ ─ ─ ─ ─ ─/─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
           stop ratchets up ↑              ↑ filled
```

## Usage

```python
from decimal import Decimal
from trading_platform.orders.trailing_stop import TrailingStopManager

tsm = TrailingStopManager(event_bus, exec_adapter)
await tsm.wire_events()

# Trail by absolute amount ($2.00)
ts = await tsm.create_trailing_stop(
    symbol="AAPL",
    quantity=Decimal("100"),
    current_price=Decimal("155.00"),
    trail_amount=Decimal("2.00"),
)
# Stop placed at 153.00

# Trail by percentage (1.5%)
ts = await tsm.create_trailing_stop(
    symbol="AAPL",
    quantity=Decimal("100"),
    current_price=Decimal("155.00"),
    trail_percent=Decimal("1.5"),
)
# Stop placed at 155 - (155 * 0.015) = 152.675
```

### Query and Cancel

```python
# Get a specific trailing stop
ts = tsm.get_trailing_stop("ts-001")

# Get all active trailing stops
active = tsm.get_active_trailing_stops()

# Cancel
await tsm.cancel_trailing_stop("ts-001")
```

## States

| State | Description |
|-------|-------------|
| `PENDING` | Created, stop not yet placed |
| `ACTIVE` | Stop order is live, monitoring quotes |
| `COMPLETED` | Stop triggered and filled |
| `CANCELED` | Manually canceled |
| `ERROR` | Error during lifecycle |

## Event Channels

| Channel | Description |
|---------|-------------|
| `trailing_stop.placed` | Initial stop order placed |
| `trailing_stop.updated` | Stop price ratcheted up via cancel-and-replace |
| `trailing_stop.completed` | Stop triggered and filled |
| `trailing_stop.canceled` | Trailing stop canceled |
| `trailing_stop.error` | Error occurred |
| `trailing_stop.state_change` | State transition |

## Configuration

Trailing stops are managed programmatically — no config.toml section is needed. Create them via `TrailingStopManager.create_trailing_stop()` or through `StrategyContext`.

## Integration with Bracket Orders

Bracket orders can use trailing stops instead of fixed stop-losses. When `trailing_stop=True` is set on a bracket, the stop-loss leg becomes a trailing stop managed by `TrailingStopManager`.
