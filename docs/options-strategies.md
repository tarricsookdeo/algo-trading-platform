# Options Strategies

## Overview

The `OptionsStrategyBuilder` constructs common multi-leg options strategies, validates parameters, and returns `MultiLegOrder` objects ready for submission.

## Supported Strategies

| Strategy | Description | Legs |
|----------|-------------|------|
| **Vertical Spread** | Bull/bear call or put spread | 2 |
| **Iron Condor** | Short strangle + long strangle protection | 4 |
| **Straddle** | Same strike call + put | 2 |
| **Strangle** | Different strike call + put | 2 |
| **Butterfly Spread** | Three-strike spread | 3 |
| **Calendar Spread** | Same strike, different expirations | 2 |

## Usage

```python
from decimal import Decimal
from datetime import date
from trading_platform.options.strategy_builder import OptionsStrategyBuilder
from trading_platform.options.strategies import (
    VerticalSpreadParams, IronCondorParams, StraddleParams,
    StrangleParams, ButterflySpreadParams, CalendarSpreadParams,
)
from trading_platform.core.enums import ContractType

builder = OptionsStrategyBuilder()
```

### Vertical Spread

```python
params = VerticalSpreadParams(
    underlying="AAPL",
    expiration=date(2025, 3, 21),
    long_strike=Decimal("150"),
    short_strike=Decimal("160"),
    contract_type=ContractType.CALL,
    quantity=Decimal("1"),
)
order = builder.build_vertical_spread(params)
```

### Iron Condor

```python
params = IronCondorParams(
    underlying="SPY",
    expiration=date(2025, 3, 21),
    put_long_strike=Decimal("440"),
    put_short_strike=Decimal("445"),
    call_short_strike=Decimal("460"),
    call_long_strike=Decimal("465"),
    quantity=Decimal("1"),
)
order = builder.build_iron_condor(params)
```

### Straddle

```python
params = StraddleParams(
    underlying="AAPL",
    expiration=date(2025, 3, 21),
    strike=Decimal("150"),
    quantity=Decimal("1"),
    side="long",  # or "short"
)
order = builder.build_straddle(params)
```

### Strangle

```python
params = StrangleParams(
    underlying="AAPL",
    expiration=date(2025, 3, 21),
    put_strike=Decimal("145"),
    call_strike=Decimal("155"),
    quantity=Decimal("1"),
    side="long",
)
order = builder.build_strangle(params)
```

### Butterfly Spread

```python
params = ButterflySpreadParams(
    underlying="AAPL",
    expiration=date(2025, 3, 21),
    lower_strike=Decimal("145"),
    middle_strike=Decimal("150"),
    upper_strike=Decimal("155"),
    contract_type=ContractType.CALL,
    quantity=Decimal("1"),
)
order = builder.build_butterfly_spread(params)
```

### Calendar Spread

```python
params = CalendarSpreadParams(
    underlying="AAPL",
    expiration_near=date(2025, 3, 21),
    expiration_far=date(2025, 4, 18),
    strike=Decimal("150"),
    contract_type=ContractType.CALL,
    quantity=Decimal("1"),
)
order = builder.build_calendar_spread(params)
```

## Validation

The `StrategyValidator` checks parameters before building orders:

```python
from trading_platform.options.validator import StrategyValidator

validator = StrategyValidator()
analysis = validator.validate_vertical_spread(params)

if analysis.is_valid:
    print(f"Max profit: {analysis.max_profit}")
    print(f"Max loss: {analysis.max_loss}")
    print(f"Breakevens: {analysis.breakevens}")
else:
    print(f"Errors: {analysis.errors}")
```

### Validation Checks

- Strike prices are in correct order for each strategy
- All legs use the same underlying and correct expirations
- Quantity consistency across legs
- Quantity is positive
- Expiration dates are valid

### StrategyAnalysis

| Field | Type | Description |
|-------|------|-------------|
| `max_profit` | `Decimal \| None` | Maximum potential profit |
| `max_loss` | `Decimal \| None` | Maximum potential loss |
| `breakevens` | `list[Decimal]` | Breakeven price points |
| `errors` | `list[str]` | Validation errors |
| `is_valid` | `bool` | True if no errors |

## Build and Submit

Use `build_and_submit()` for a one-step build + route:

```python
order = await builder.build_and_submit(params, order_router)
```

## Integration with Strategies

Strategies can use the builder via `StrategyContext`:

```python
class MyOptionsStrategy(Strategy):
    async def on_bar(self, bar: Bar) -> None:
        if self.should_sell_iron_condor(bar):
            params = IronCondorParams(...)
            order = self.builder.build_iron_condor(params)
            await self.context.submit_multileg_order(order)
```
