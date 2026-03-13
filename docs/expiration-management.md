# Expiration Management

## Overview

The `ExpirationManager` monitors days-to-expiration (DTE) for all open options positions and can automatically close or roll positions approaching expiration.

## How It Works

1. The manager tracks all options positions and their expiration dates
2. A background loop checks DTE at a configurable interval
3. When a position reaches `alert_dte`, an `options.expiration.warning` event is emitted
4. When a position reaches `auto_close_dte`, the position is automatically closed
5. If `roll_enabled` is true, the manager attempts to roll the position to the next expiration

## Configuration

### config.toml

```toml
[options.expiration]
auto_close_dte = 1        # Close positions at 1 DTE to avoid assignment
alert_dte = 7             # Alert when position reaches 7 DTE
roll_enabled = false      # Attempt to roll on auto-close
roll_target_dte = 30      # Target DTE for rolled positions
check_interval_seconds = 60.0  # How often to check
```

### ExpirationConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_close_dte` | `int` | `1` | Auto-close at N DTE |
| `alert_dte` | `int` | `7` | Emit warning at N DTE |
| `roll_enabled` | `bool` | `false` | Attempt position rolling |
| `roll_target_dte` | `int` | `30` | Target DTE for rolls |
| `check_interval_seconds` | `float` | `60.0` | Check interval |

## Usage

```python
from trading_platform.options.expiration import ExpirationManager, ExpirationConfig

config = ExpirationConfig(
    auto_close_dte=1,
    alert_dte=7,
    roll_enabled=True,
    roll_target_dte=30,
)

manager = ExpirationManager(
    config=config,
    event_bus=event_bus,
    exec_adapter=options_adapter,
    strategy_builder=options_strategy_builder,
)

await manager.start()
```

### Manual Position Tracking

```python
from trading_platform.options.expiration import OptionsPosition
from trading_platform.core.enums import ContractType
from datetime import date

positions = [
    OptionsPosition(
        symbol="AAPL250321C00150000",
        underlying="AAPL",
        quantity=5,
        contract_type=ContractType.CALL,
        strike_price=150.0,
        expiration_date=date(2025, 3, 21),
    ),
]
manager.set_positions(positions)
```

### Manual Check

```python
await manager.check_expirations()
```

## Event Channels

| Channel | Payload | Description |
|---------|---------|-------------|
| `options.expiration.warning` | `{symbol, underlying, dte, expiration_date}` | Position approaching expiration |
| `options.position.auto_closed` | `{symbol, underlying, quantity, dte}` | Position auto-closed |
| `options.position.rolled` | `{symbol, new_symbol, underlying}` | Position rolled to next expiration |

## Rolling Logic

When `roll_enabled=true` and a position reaches `auto_close_dte`:

1. Close the current position
2. Find the next available expiration at or near `roll_target_dte`
3. Open the same strategy at the new expiration
4. If the position is part of a multi-leg strategy, the `OptionsStrategyBuilder` reconstructs the strategy at the new expiration

## Dashboard

The dashboard shows:
- **Expiration countdown** — DTE badges (green > 14 DTE, orange 7-14 DTE, red < 7 DTE)
- **Position details** — Symbol, underlying, strike, contract type, expiration date
- **Auto-close alerts** in the event log

## See Also

- [Options Trading](options-trading.md) — Options order model and adapter
- [Options Strategies](options-strategies.md) — Strategy builder for rolling
- [Greeks & Risk](greeks-risk.md) — Greeks monitoring for options positions
