# Scaled Orders

## Overview

The `ScaledOrderManager` handles multi-tranche entries and exits. Instead of a single take-profit or entry price, you define multiple price levels with quantity allocations.

## Scaled Exits

Sell a position in tranches at multiple take-profit levels:

```python
from decimal import Decimal
from trading_platform.orders.scaled import ScaledOrderManager

som = ScaledOrderManager(event_bus, exec_adapter)
await som.wire_events()

# Sell 100 shares in 3 tranches
exit_order = await som.create_scaled_exit(
    symbol="AAPL",
    total_quantity=Decimal("100"),
    take_profit_levels=[
        (Decimal("155.00"), Decimal("50")),   # 50 shares at $155
        (Decimal("160.00"), Decimal("30")),   # 30 shares at $160
        (Decimal("165.00"), Decimal("20")),   # 20 shares at $165
    ],
    stop_loss_price=Decimal("145.00"),
)
```

### How Scaled Exits Work

1. A stop-loss order is placed for the full position
2. The manager monitors bid prices via quotes
3. When bid >= tranche price, that tranche executes (market sell)
4. After each tranche fills, the stop-loss is adjusted for the remaining quantity
5. If stop-loss triggers, the remaining position sells at the stop price

## Scaled Entries

Buy a position in tranches at multiple entry levels:

```python
entry_order = await som.create_scaled_entry(
    symbol="AAPL",
    total_quantity=Decimal("100"),
    entry_levels=[
        (Decimal("150.00"), Decimal("50")),  # 50 shares at $150
        (Decimal("148.00"), Decimal("30")),  # 30 shares at $148
        (Decimal("145.00"), Decimal("20")),  # 20 shares at $145
    ],
    stop_loss_price=Decimal("140.00"),
)
```

### How Scaled Entries Work

1. Limit orders are placed at each entry level
2. When any tranche fills, a stop-loss is placed sized to the filled quantity
3. As more tranches fill, the stop-loss is adjusted for the total filled quantity
4. When all tranches fill, the entry is complete

## States

| State | Description |
|-------|-------------|
| `PENDING` | Created, orders not yet placed |
| `ACTIVE` | Orders are live, monitoring for fills |
| `COMPLETED` | All tranches filled (or stopped out) |
| `CANCELED` | Manually canceled |
| `ERROR` | Error during lifecycle |

## Event Channels

| Channel | Description |
|---------|-------------|
| `scaled.exit.placed` | Scaled exit created |
| `scaled.exit.tranche_filled` | Exit tranche filled |
| `scaled.exit.completed` | All exit tranches filled |
| `scaled.exit.stopped_out` | Stop-loss hit on remaining position |
| `scaled.entry.placed` | Scaled entry created |
| `scaled.entry.tranche_filled` | Entry tranche filled |
| `scaled.entry.completed` | All entry tranches filled |
| `scaled.stop.adjusted` | Stop-loss adjusted after tranche fill |
| `scaled.state_change` | State transition |
| `scaled.error` | Error |
| `scaled.canceled` | Scaled order canceled |

## Dashboard

The dashboard shows scaled order progress with:
- Tranche bar visualization showing filled/unfilled segments
- Remaining quantity tracker
- Stop-loss price display
- State badge
