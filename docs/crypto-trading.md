# Crypto Trading

## Overview

The platform supports cryptocurrency trading via Public.com's crypto API endpoints. The `CryptoExecAdapter` implements the `ExecAdapter` interface, enabling crypto orders to flow through the same event-driven architecture as equity and options orders.

## Configuration

### config.toml

```toml
[crypto]
trading_pairs = ["BTC-USD", "ETH-USD", "SOL-USD"]
poll_interval = 2.0
portfolio_refresh = 30.0
```

### Environment Variables

Crypto trading uses the same Public.com credentials as equities:

| Variable | Description |
|----------|-------------|
| `PUBLIC_API_SECRET` | Public.com API secret |
| `PUBLIC_ACCOUNT_ID` | Public.com account ID |

## CryptoExecAdapter

`trading_platform.adapters.crypto.adapter.CryptoExecAdapter`

### Setup

```python
from trading_platform.adapters.crypto.config import CryptoConfig
from trading_platform.adapters.crypto.adapter import CryptoExecAdapter
from trading_platform.core.events import EventBus

config = CryptoConfig(
    api_secret="your_api_secret",
    account_id="your_account_id",
    trading_pairs=["BTC-USD", "ETH-USD"],
)
bus = EventBus()
adapter = CryptoExecAdapter(config, bus)
await adapter.connect()
```

### Placing Orders

```python
from decimal import Decimal
from trading_platform.core.models import Order
from trading_platform.core.enums import OrderSide, OrderType, AssetClass

# Market buy 0.005 BTC
order = Order(
    symbol="BTC-USD",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    quantity=Decimal("0.005"),
    asset_class=AssetClass.CRYPTO,
)
result = await adapter.submit_order(order)

# Limit sell 1.5 ETH
order = Order(
    symbol="ETH-USD",
    side=OrderSide.SELL,
    order_type=OrderType.LIMIT,
    quantity=Decimal("1.5"),
    limit_price=3500.00,
    asset_class=AssetClass.CRYPTO,
)
result = await adapter.submit_order(order)
```

### Portfolio

```python
positions = await adapter.get_positions()
account = await adapter.get_account()
```

## Key Differences from Equities

| Feature | Equities | Crypto |
|---------|----------|--------|
| **Quantities** | Whole shares (or fractional via broker) | Fractional (e.g., 0.005 BTC) |
| **Symbol format** | Ticker (AAPL) | Pair (BTC-USD) |
| **Trading hours** | Market hours only | 24/7 |
| **Order types** | Market, limit, stop, stop_limit | Market, limit |

## Order Routing

When using the `OrderRouter`, set `asset_class=AssetClass.CRYPTO` on the order to route to the crypto adapter:

```python
from trading_platform.core.order_router import OrderRouter

router = OrderRouter()
router.register(AssetClass.CRYPTO, crypto_adapter)

order = Order(symbol="BTC-USD", asset_class=AssetClass.CRYPTO, ...)
await router.submit_order(order)  # Routes to CryptoExecAdapter
```

## Event Channels

The crypto adapter publishes to the same `execution.*` channels as the equity adapter:

| Channel | Description |
|---------|-------------|
| `execution.order.submitted` | Crypto order accepted |
| `execution.order.filled` | Crypto order filled |
| `execution.order.cancelled` | Crypto order cancelled |
| `execution.order.rejected` | Crypto order rejected |
| `execution.portfolio.update` | Crypto portfolio sync |

## Dashboard

The dashboard displays crypto positions alongside equity positions with:
- Fractional quantity display
- `CRYPTO` asset class badge
- Standard P&L columns
