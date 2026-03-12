# Adapters Guide

The platform uses two adapters: **AlpacaDataAdapter** for real-time market data and **PublicComExecAdapter** for order execution. Both communicate exclusively through the EventBus.

## Alpaca Data Adapter

`trading_platform.adapters.alpaca.adapter.AlpacaDataAdapter`

The Alpaca adapter provides real-time market data via WebSocket streams and historical data via REST.

### Components

| Component | Class | Description |
|-----------|-------|-------------|
| Facade | `AlpacaDataAdapter` | Unified interface implementing `DataAdapter` ABC |
| Stock stream | `AlpacaStockStream` | SIP/IEX WebSocket (JSON) — quotes, trades, bars, status, LULD |
| Options stream | `AlpacaOptionsStream` | OPRA WebSocket (msgpack) — option quotes and trades |
| REST client | `AlpacaClient` | Historical bars, snapshots, latest quotes/trades |
| Instrument provider | `AlpacaInstrumentProvider` | Load and search tradable instruments |
| Parsers | `parse_stock_*`, `parse_option_*` | Convert raw messages to domain models |

### SIP Stock Stream

Connects to `wss://stream.data.alpaca.markets/v2/sip` (or `/v2/iex` for the free feed).

**Data types:**

| Type | Domain Model | EventBus Channel |
|------|-------------|------------------|
| Quotes | `QuoteTick` | `Channel.QUOTE` |
| Trades | `TradeTick` | `Channel.TRADE` |
| Bars | `Bar` | `Channel.BAR` |
| Trading status | `TradingStatus` | `Channel.STATUS` |
| LULD bands | `LULD` | `Channel.STATUS` |

**Features:**
- Automatic authentication on connect
- Reconnection with exponential backoff
- Tracks `messages_received`, `last_message_time`, `reconnect_count`

### OPRA Options Stream

Connects to `wss://stream.data.alpaca.markets/v1beta1/opra`. Messages are msgpack-encoded for bandwidth efficiency.

**Limits:** Maximum 1,000 quote subscriptions (`MAX_QUOTE_SUBSCRIPTIONS`).

**Data types:**

| Type | Domain Model | EventBus Channel |
|------|-------------|------------------|
| Option quotes | `QuoteTick` | `Channel.QUOTE` |
| Option trades | `TradeTick` | `Channel.TRADE` |

### REST Client

`AlpacaClient` provides historical and snapshot data via HTTP:

```python
from trading_platform.adapters.alpaca.client import AlpacaClient
from trading_platform.adapters.alpaca.config import AlpacaConfig

config = AlpacaConfig(api_key="...", api_secret="...")
client = AlpacaClient(config)
await client.start()

# Historical bars
bars = await client.get_bars("AAPL", timeframe="1Min", limit=100)

# Latest quote
quote = await client.get_latest_quote("AAPL")

# Snapshot (latest trade, quote, bar)
snapshot = await client.get_snapshot("AAPL")

# Historical trades
trades = await client.get_trades("AAPL", limit=50)

# Historical quotes
quotes = await client.get_quotes("AAPL", limit=50)

await client.close()
```

**Methods:**

| Method | Description |
|--------|-------------|
| `get_bars(symbol, timeframe, start, end, limit, feed, adjustment)` | Historical bars |
| `get_trades(symbol, start, end, limit, feed)` | Historical trades |
| `get_quotes(symbol, start, end, limit, feed)` | Historical quotes |
| `get_snapshot(symbol, feed)` | Latest snapshot (trade + quote + bar) |
| `get_latest_trade(symbol, feed)` | Most recent trade |
| `get_latest_quote(symbol, feed)` | Most recent quote |

Rate limit: 10,000 requests/minute with automatic retry (up to 5 retries).

### Instrument Provider

```python
from trading_platform.adapters.alpaca.provider import AlpacaInstrumentProvider

provider = AlpacaInstrumentProvider(config)
await provider.start()

# Load all stock instruments
count = await provider.load_stock_instruments()

# Look up by symbol
instrument = provider.get_instrument("AAPL")

# Search by name or symbol
results = provider.search("Apple")

# Get all loaded instruments
all_instruments = provider.get_all_instruments()

await provider.close()
```

### Subscription Management

```python
# Subscribe to data
await adapter.subscribe_quotes(["AAPL", "MSFT"])
await adapter.subscribe_trades(["AAPL", "MSFT"])
await adapter.subscribe_bars(["AAPL", "MSFT"])

# Unsubscribe
await adapter.unsubscribe(["MSFT"])
```

### Reconnection and Error Handling

- WebSocket streams auto-reconnect with exponential backoff
- REST client retries failed requests up to `MAX_RETRIES` (5)
- Parse errors are logged but don't crash the stream
- Connection errors are published to `Channel.ERROR`

---

## Public.com Execution Adapter

`trading_platform.adapters.public_com.adapter.PublicComExecAdapter`

The execution adapter uses the `publicdotcom-py` SDK (`public_api_sdk`) for live order execution.

### Authentication

```python
from trading_platform.adapters.public_com.config import PublicComConfig
from trading_platform.adapters.public_com.adapter import PublicComExecAdapter
from trading_platform.core.events import EventBus

config = PublicComConfig(
    api_secret="your_api_secret",
    account_id="your_account_id",
)
bus = EventBus()
adapter = PublicComExecAdapter(config, bus)
await adapter.connect()
```

Authentication uses `ApiKeyAuthConfig` from the SDK with automatic token refresh. The `token_validity_minutes` config (default: 15) controls refresh frequency.

### Order Placement

#### Single-Leg Equity Order

```python
from trading_platform.core.models import Order
from trading_platform.core.enums import OrderSide, OrderType

order = Order(
    symbol="AAPL",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=10.0,
    limit_price=150.00,
)
result = await adapter.submit_order(order)
```

#### Single-Leg Option Order

Options are detected by symbol length (> 10 characters = OCC option symbol):

```python
order = Order(
    symbol="AAPL250321C00150000",  # OCC format
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=1.0,
    limit_price=5.00,
)
result = await adapter.submit_order(order)
```

#### Multi-Leg Spread Order

```python
from public_api_sdk.models import (
    MultilegOrderRequest,
    OrderLegRequest,
    LegInstrument,
    LegInstrumentType,
    OrderExpirationRequest,
    TimeInForce,
    OpenCloseIndicator,
)
from decimal import Decimal

request = MultilegOrderRequest(
    order_id="spread-001",
    legs=[
        OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL250321C00150000",
                type=LegInstrumentType.OPTION,
            ),
            side=SDKOrderSide.BUY,
            quantity=Decimal("1"),
            open_close_indicator=OpenCloseIndicator.OPEN,
        ),
        OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL250321C00160000",
                type=LegInstrumentType.OPTION,
            ),
            side=SDKOrderSide.SELL,
            quantity=Decimal("1"),
            open_close_indicator=OpenCloseIndicator.OPEN,
        ),
    ],
    order_type=SDKOrderType.LIMIT,
    limit_price=Decimal("2.50"),
    expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
)
result = await adapter.submit_multileg_order(request)
```

### Order Lifecycle

```
submit_order() → execution.order.submitted
                      │
          ┌───────────┼───────────┬──────────────┐
          ▼           ▼           ▼              ▼
    .filled    .partially_filled  .cancelled   .rejected
```

The adapter starts an async tracker (`_track_order`) for each submitted order that polls for status updates until reaching a terminal state (FILLED, CANCELLED, REJECTED, EXPIRED, REPLACED).

### Cancel and Cancel-and-Replace

```python
# Cancel
await adapter.cancel_order("order-id-123")

# Cancel and replace
from public_api_sdk.models import CancelAndReplaceRequest

request = CancelAndReplaceRequest(
    original_order_id="order-id-123",
    order_type=SDKOrderType.LIMIT,
    limit_price=Decimal("155.00"),
    quantity=Decimal("10"),
)
result = await adapter.cancel_and_replace(request)
```

### Preflight Checks

Run a cost estimation before placing an order:

```python
cost = await adapter.perform_preflight(order)
```

### Portfolio Sync

The adapter runs a background loop (every `portfolio_refresh` seconds) that:

1. Fetches positions from Public.com
2. Fetches buying power and equity
3. Publishes `execution.portfolio.update` with positions and account data
4. Publishes `execution.account.update` with account info

Manual sync:

```python
await adapter.sync_portfolio()
positions = await adapter.get_positions()  # Returns cached positions
account = await adapter.get_account()      # Returns cached account info
```

### Error Handling

| Error | Behavior |
|-------|----------|
| `RateLimitError` | Logged with `retry_after`, publishes `execution.order.error`, re-raises |
| `APIError` | Logged, publishes `execution.order.error`, re-raises |
| Auth failure | Raised on `connect()` |
| Network error | Logged in portfolio sync loop, retried next cycle |

### Event Publishing

The adapter publishes to these channels:

| Channel | When |
|---------|------|
| `execution.order.submitted` | Order accepted by API |
| `execution.order.filled` | Order fully filled |
| `execution.order.partially_filled` | Partial fill |
| `execution.order.cancelled` | Order cancelled |
| `execution.order.rejected` | Order rejected |
| `execution.order.error` | API error, rate limit, cancel failure |
| `execution.portfolio.update` | Portfolio sync completed |
| `execution.account.update` | Account info updated |

---

## Writing Custom Adapters

### DataAdapter ABC

To implement a custom data adapter:

```python
from trading_platform.adapters.base import DataAdapter

class MyDataAdapter(DataAdapter):
    async def connect(self) -> None:
        """Connect to the data source."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the data source."""
        ...

    async def subscribe_quotes(self, symbols: list[str]) -> None:
        """Subscribe to quote updates for symbols."""
        ...

    async def subscribe_trades(self, symbols: list[str]) -> None:
        """Subscribe to trade updates for symbols."""
        ...

    async def subscribe_bars(self, symbols: list[str]) -> None:
        """Subscribe to bar updates for symbols."""
        ...

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from all data for symbols."""
        ...

    @property
    def is_connected(self) -> bool:
        """Return True if connected to the data source."""
        ...
```

Publish parsed data to the EventBus using `Channel.QUOTE`, `Channel.TRADE`, `Channel.BAR`.

### ExecAdapter ABC

To implement a custom execution adapter:

```python
from trading_platform.adapters.base import ExecAdapter

class MyExecAdapter(ExecAdapter):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def submit_order(self, order: Order) -> Any: ...
    async def cancel_order(self, order_id: str) -> Any: ...
    async def get_positions(self) -> list[Any]: ...
    async def get_account(self) -> Any: ...
```

Publish order events to the `execution.*` channels on the EventBus.
