# Risk Management Guide

## Overview

The RiskManager sits between the strategy layer and the execution layer. Every order submitted through a `StrategyContext` passes through pre-trade risk checks before reaching the execution adapter. Post-trade checks monitor portfolio health and can trigger automatic trading halts.

```
Strategy → StrategyContext.submit_order()
                    │
                    ▼
            ┌───────────────┐
            │  RiskManager   │
            │ pre_trade_check│
            ├───────────────┤
            │ 1. Symbol check│
            │ 2. Position sz │
            │ 3. Concentration│
            │ 4. Order value │
            │ 5. Daily loss  │
            │ 6. Open orders │
            └───────┬───────┘
                    │
            ┌───────┴───────┐
            │               │
         PASS            FAIL
            │               │
            ▼               ▼
    ExecAdapter      Return None
    .submit_order()  publish("risk.check.failed")
```

## Pre-Trade Checks

All pre-trade checks run synchronously in order. If any check fails, the order is rejected immediately and no subsequent checks run.

### 1. Symbol Allowlist/Blocklist

**Check:** `check_symbol_allowed(order, config)`

| Config Field | Description |
|-------------|-------------|
| `blocked_symbols` | Orders for these symbols are always rejected |
| `allowed_symbols` | If non-empty, only these symbols are allowed |

The blocklist is checked first. If a symbol is on the blocklist, it's rejected regardless of the allowlist. If `allowed_symbols` is empty, all non-blocked symbols are allowed.

**Example rejection:** `"Symbol GME is blocked"`

### 2. Position Size Limit

**Check:** `check_position_size(order, positions, config)`

| Config Field | Default | Description |
|-------------|---------|-------------|
| `max_position_size` | 1000.0 | Maximum total shares/contracts per symbol |

Computes: `existing_quantity + order.quantity`. Rejects if total exceeds `max_position_size`.

**Example rejection:** `"Position size 1500 exceeds limit 1000 for AAPL"`

### 3. Position Concentration

**Check:** `check_position_concentration(order, positions, config, portfolio_value)`

| Config Field | Default | Description |
|-------------|---------|-------------|
| `max_position_concentration` | 0.10 | Maximum single-position value as fraction of portfolio |

Computes: `(position_market_value + order_value) / portfolio_value`. Skipped if `portfolio_value <= 0`.

**Example rejection:** `"Concentration 15.2% exceeds limit 10.0% for TSLA"`

### 4. Order Value Limit

**Check:** `check_order_value(order, config)`

| Config Field | Default | Description |
|-------------|---------|-------------|
| `max_order_value` | 50000.0 | Maximum dollar value per individual order |

Computes: `order.quantity * (order.limit_price or order.stop_price or 0.0)`.

**Example rejection:** `"Order value $75,000.00 exceeds limit $50,000.00"`

### 5. Daily Loss Limit

**Check:** `check_daily_loss(state, config)`

| Config Field | Default | Description |
|-------------|---------|-------------|
| `daily_loss_limit` | -5000.0 | Minimum daily P&L (negative number) |

Rejects new orders if `daily_pnl < daily_loss_limit`. Note: this also triggers a trading halt via `update_daily_pnl()`.

**Example rejection:** `"Daily P&L $-6,500.00 below limit $-5,000.00"`

### 6. Max Open Orders

**Check:** `check_max_open_orders(state, config)`

| Config Field | Default | Description |
|-------------|---------|-------------|
| `max_open_orders` | 20 | Maximum concurrent open orders |

Rejects if `open_order_count >= max_open_orders`.

**Example rejection:** `"Open orders 20 at limit 20"`

## Post-Trade Checks

Post-trade checks run after each trade execution via `post_trade_check()`:

### 1. Portfolio Drawdown

**Check:** `check_portfolio_drawdown(state, config)`

| Config Field | Default | Description |
|-------------|---------|-------------|
| `max_portfolio_drawdown` | 0.15 | Maximum drawdown from peak (15%) |

Computes: `(portfolio_peak - portfolio_value) / portfolio_peak`. **Triggers a trading halt** if exceeded.

**Example halt:** `"Portfolio drawdown 18.5% exceeds limit 15.0%"`

### 2. Daily Trade Count

**Check:** `check_daily_trade_count(state, config)`

| Config Field | Default | Description |
|-------------|---------|-------------|
| `max_daily_trades` | 100 | Maximum trades per day |

Publishes a `risk.alert` event if exceeded (does not halt trading).

**Example alert:** `"Daily trade count 105 exceeds limit 100"`

## Trading Halts

A trading halt prevents all new orders from being submitted. Halts are triggered by:

1. **Portfolio drawdown** exceeding `max_portfolio_drawdown`
2. **Daily loss** exceeding `daily_loss_limit`

When halted:
- `state.is_halted = True`
- `state.halt_reason` describes why
- A `RiskViolation` is recorded
- `risk.halt` event is published to the EventBus
- All subsequent `pre_trade_check()` calls return `(False, "Trading halted: ...")`

### Resuming After a Halt

Call `reset_daily()` to clear the halt and reset daily counters:

```python
await risk_manager.reset_daily()
```

This resets:
- `daily_pnl` to 0.0
- `daily_trade_count` to 0
- `is_halted` to False
- `halt_reason` to ""

Typically called at the start of each trading day.

## Risk State Model

`trading_platform.risk.models.RiskState`

| Field | Type | Description |
|-------|------|-------------|
| `is_halted` | `bool` | Whether trading is halted |
| `halt_reason` | `str` | Reason for the halt |
| `daily_pnl` | `float` | Realized P&L for the current day |
| `daily_trade_count` | `int` | Number of trades executed today |
| `portfolio_peak` | `float` | Highest portfolio value seen (for drawdown) |
| `portfolio_value` | `float` | Current portfolio value |
| `open_order_count` | `int` | Number of currently open orders |
| `violations` | `list[RiskViolation]` | History of all risk violations |

## Risk Violations

Each failed check or halt creates a `RiskViolation`:

```python
class RiskViolation(BaseModel):
    check_name: str        # "pre_trade" or "halt"
    message: str           # Human-readable description
    order_id: str = ""     # Related order ID (if applicable)
    symbol: str = ""       # Related symbol (if applicable)
    timestamp: datetime    # When the violation occurred
    data: dict = {}        # Additional context
```

Violations are accessible via:
- `risk_manager.get_violations()` — returns list of dicts
- `risk_manager.state.violations` — returns list of `RiskViolation` objects
- Dashboard API: `GET /api/risk/violations`

## Event Channels

| Channel | Payload | Description |
|---------|---------|-------------|
| `risk.check.passed` | `{strategy_id, order_id}` | Pre-trade check passed |
| `risk.check.failed` | `{order_id, reason}` | Pre-trade check failed |
| `risk.alert` | `{type, message, ...}` | Non-halting risk alert |
| `risk.halt` | `{reason}` | Trading halted |

## Configuration Examples

### Conservative

For small accounts or initial deployment:

```toml
[risk]
max_position_size = 100.0
max_position_concentration = 0.05    # 5% max per position
max_order_value = 5000.0
daily_loss_limit = -500.0
max_open_orders = 5
max_daily_trades = 20
max_portfolio_drawdown = 0.05        # 5% drawdown halt
allowed_symbols = ["AAPL", "MSFT", "GOOGL"]
blocked_symbols = []
```

### Moderate

Balanced risk for active trading:

```toml
[risk]
max_position_size = 500.0
max_position_concentration = 0.10    # 10% max per position
max_order_value = 25000.0
daily_loss_limit = -2500.0
max_open_orders = 15
max_daily_trades = 75
max_portfolio_drawdown = 0.10        # 10% drawdown halt
```

### Aggressive

For larger accounts:

```toml
[risk]
max_position_size = 5000.0
max_position_concentration = 0.25    # 25% max per position
max_order_value = 100000.0
daily_loss_limit = -25000.0
max_open_orders = 50
max_daily_trades = 500
max_portfolio_drawdown = 0.20        # 20% drawdown halt
```

## Programmatic Risk Configuration

```python
from trading_platform.risk.models import RiskConfig
from trading_platform.risk.manager import RiskManager
from trading_platform.core.events import EventBus

config = RiskConfig(
    max_position_size=500.0,
    max_position_concentration=0.10,
    max_order_value=25000.0,
    daily_loss_limit=-2500.0,
    max_open_orders=15,
    max_daily_trades=75,
    max_portfolio_drawdown=0.10,
    blocked_symbols=["GME", "AMC"],
)

bus = EventBus()
manager = RiskManager(config, bus)

# Update portfolio tracking
await manager.update_portfolio_value(100000.0)
await manager.update_daily_pnl(-1500.0)
manager.update_open_order_count(3)

# Check current state
state = manager.get_risk_state()
violations = manager.get_violations()
```
