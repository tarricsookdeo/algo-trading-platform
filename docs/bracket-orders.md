# Bracket Orders

Synthetic bracket orders manage an entry + stop-loss + take-profit lifecycle at the framework level. This is necessary because Public.com cannot have both a stop-loss and take-profit order resting simultaneously for the same shares (shares get reserved by each sell order).

## How It Works

1. **Entry** — Place a market or limit buy order
2. **Stop-loss** — After full entry fill, place a resting stop order on the exchange
3. **Take-profit** — Framework monitors bid price from the BYOD data stream; when bid >= target, cancel the stop-loss and place a market sell

The stop-loss is always a live resting order for protection. The take-profit is synthetic — managed by watching quote data.

## State Machine

```
PENDING_ENTRY → ENTRY_PLACED → ENTRY_FILLED → STOP_LOSS_PLACED → MONITORING
                     │                                                │
                     ▼                                    ┌───────────┴───────────┐
              ENTRY_REJECTED                              ▼                       ▼
                     │                             STOPPED_OUT          TAKE_PROFIT_TRIGGERED
                     ▼                                                           │
                  CANCELED                                                       ▼
                                                                        TAKE_PROFIT_FILLED
```

Error or cancel can occur at any non-terminal state. Terminal states: `TAKE_PROFIT_FILLED`, `STOPPED_OUT`, `CANCELED`, `ENTRY_REJECTED`, `ERROR`.

## Usage from a Strategy

Bracket orders are accessible through `StrategyContext`:

```python
from decimal import Decimal
from trading_platform.core.enums import OrderType
from trading_platform.strategy.base import Strategy
from trading_platform.core.models import Bar

class MyStrategy(Strategy):
    @property
    def name(self) -> str:
        return "my-bracket-strategy"

    async def on_bar(self, bar: Bar) -> None:
        if self._should_enter(bar):
            bracket = await self.context.submit_bracket_order(
                symbol=bar.symbol,
                quantity=100,
                entry_type=OrderType.MARKET,
                stop_loss_price=Decimal("145.00"),
                take_profit_price=Decimal("160.00"),
            )
            if bracket:
                self._log.info("bracket submitted", bracket_id=bracket.bracket_id)

    async def on_bar(self, bar: Bar) -> None: ...
    async def on_quote(self, quote) -> None: ...
    async def on_trade(self, trade) -> None: ...
```

### Limit Entry

```python
bracket = await self.context.submit_bracket_order(
    symbol="AAPL",
    quantity=50,
    entry_type=OrderType.LIMIT,
    entry_limit_price=Decimal("150.00"),
    stop_loss_price=Decimal("145.00"),
    take_profit_price=Decimal("160.00"),
)
```

### Canceling a Bracket

```python
cancelled = await self.context.cancel_bracket_order(bracket.bracket_id)
```

This cancels whichever child order is currently active (entry or stop-loss) and transitions the bracket to `CANCELED`.

## Validation Rules

- `stop_loss_price < take_profit_price` (required)
- `entry_limit_price` required when `entry_type` is `LIMIT`
- For limit entries: `stop_loss_price < entry_limit_price < take_profit_price`
- `quantity > 0`
- Execution adapter must be configured

## Events

The `BracketOrderManager` publishes events on these channels:

| Channel | When | Payload |
|---------|------|---------|
| `bracket.entry.filled` | Entry order fills | `bracket_id`, `symbol`, `quantity`, `fill_price` |
| `bracket.stop.placed` | Stop-loss order placed | `bracket_id`, `stop_loss_order_id`, `stop_loss_price` |
| `bracket.stopped_out` | Stop-loss fills | `bracket_id`, `symbol`, `exit_price` |
| `bracket.take_profit.triggered` | Bid reaches target | `bracket_id`, `symbol` |
| `bracket.take_profit.filled` | Take-profit sell fills | `bracket_id`, `symbol`, `exit_price` |
| `bracket.canceled` | Bracket canceled | `bracket_id`, `reason` |
| `bracket.error` | Error during lifecycle | `bracket_id`, `error` |
| `bracket.state_change` | Any state transition | `bracket_id`, `symbol`, `from_state`, `to_state` |

Subscribe to bracket events via the EventBus:

```python
await event_bus.subscribe("bracket.state_change", my_callback)
await event_bus.subscribe("bracket.*", my_wildcard_callback)  # all bracket events
```

## Architecture

The `BracketOrderManager` sits between the strategy layer and the execution adapter:

- **Subscribes to**: `execution.order.filled`, `execution.order.cancelled`, `execution.order.rejected`, `execution.order.partially_filled`, `quote`
- **Publishes to**: `bracket.*` channels
- **Uses**: `ExecAdapter.submit_order()` and `ExecAdapter.cancel_order()` for child orders

The manager maintains reverse-lookup maps from child order IDs to bracket IDs for efficient event routing. A `_monitored_symbols` set filters quote events to only process symbols with active brackets in the MONITORING state.

## Edge Cases

- **Partial fills**: The manager waits for a full entry fill before placing the stop-loss. Partial fills are ignored.
- **Stop cancel fails during take-profit**: If canceling the stop-loss fails (e.g., it already filled), the bracket transitions to `STOPPED_OUT` rather than attempting the take-profit sell.
- **Race condition**: If the stop-loss fills at the same time the bid hits the take-profit target, the fill event takes precedence since the stop was a real resting order.
- **No exec adapter**: `submit_bracket_order()` raises `RuntimeError` if no execution adapter is configured. From the strategy layer, `StrategyContext.submit_bracket_order()` returns `None`.
