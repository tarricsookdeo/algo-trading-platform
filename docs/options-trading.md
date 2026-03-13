# Options Trading

## Overview

The platform supports single-leg and multi-leg options trading via Public.com. The `OptionsExecAdapter` handles order submission, position management, and option chain queries.

## Order Model

Options orders use additional fields on the `Order` model:

```python
from decimal import Decimal
from datetime import date
from trading_platform.core.models import Order
from trading_platform.core.enums import OrderSide, OrderType, AssetClass, ContractType

order = Order(
    symbol="AAPL250321C00150000",  # OCC symbol
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=Decimal("1"),
    limit_price=5.00,
    asset_class=AssetClass.OPTION,
    contract_type=ContractType.CALL,
    strike_price=Decimal("150"),
    expiration_date=date(2025, 3, 21),
    underlying_symbol="AAPL",
    option_symbol="AAPL250321C00150000",
)
```

### Options-Specific Fields

| Field | Type | Description |
|-------|------|-------------|
| `asset_class` | `AssetClass.OPTION` | Identifies as options order |
| `contract_type` | `ContractType` | CALL or PUT |
| `strike_price` | `Decimal` | Strike price |
| `expiration_date` | `date` | Expiration date |
| `underlying_symbol` | `str` | Underlying ticker (e.g., "AAPL") |
| `option_symbol` | `str` | OCC option symbol |

## Multi-Leg Orders

The `MultiLegOrder` model represents multi-leg strategies:

```python
from trading_platform.core.models import MultiLegOrder

spread = MultiLegOrder(
    legs=[long_call, short_call],
    strategy_type="VERTICAL_SPREAD",
    net_debit_or_credit=Decimal("2.50"),
)
result = await adapter.submit_multileg_order(spread)
```

### MultiLegOrder Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Order identifier |
| `legs` | `list[Order]` | Individual option legs |
| `strategy_type` | `str` | Strategy name (e.g., "VERTICAL_SPREAD", "IRON_CONDOR") |
| `net_debit_or_credit` | `Decimal` | Net premium |
| `status` | `OrderStatus` | Overall order status |

## OptionsExecAdapter

### Configuration

```python
from trading_platform.adapters.options.config import OptionsConfig
from trading_platform.adapters.options.adapter import OptionsExecAdapter

config = OptionsConfig(
    api_secret="your_api_secret",
    account_id="your_account_id",
)
adapter = OptionsExecAdapter(config, event_bus)
await adapter.connect()
```

### Methods

| Method | Description |
|--------|-------------|
| `submit_option_order(order)` | Submit a single-leg option order |
| `submit_multileg_order(multileg)` | Submit a multi-leg strategy |
| `cancel_option_order(order_id)` | Cancel an options order |
| `get_option_positions()` | Get current options positions |
| `preflight_option_order(order)` | Cost estimation |
| `get_option_chain(underlying)` | Available options contracts |
| `get_option_expirations(underlying)` | Available expiration dates |

### config.toml

```toml
[options]
poll_interval = 2.0
portfolio_refresh = 30.0
```

## Order Routing

Set `asset_class=AssetClass.OPTION` to route through the `OrderRouter`:

```python
router.register(AssetClass.OPTION, options_adapter)
await router.submit_order(option_order)       # Single-leg
await router.submit_multileg_order(spread)    # Multi-leg
```

## See Also

- [Options Strategies](options-strategies.md) — Strategy builder for verticals, iron condors, etc.
- [Greeks & Risk](greeks-risk.md) — Greeks-aware risk checks
- [Expiration Management](expiration-management.md) — DTE monitoring and auto-close
