# Data Providers & Adapters Guide

The platform uses a **bring-your-own-data (BYOD)** architecture for market data and **PublicComExecAdapter** for order execution. All data flows through the EventBus.

## Data Ingestion Overview

Data enters the platform through three paths:

| Path | Use Case |
|------|----------|
| **File providers** (CSV) | Historical data replay and warm-starting strategies |
| **REST/WebSocket ingestion** | External systems pushing data in real time |
| **Custom DataProvider** | Any data source via Python |

All paths publish to the same EventBus channels (`quote`, `trade`, `bar`), so strategies and the dashboard work identically regardless of data source.

---

## DataProvider ABC

`trading_platform.data.provider.DataProvider`

All data providers implement this interface:

```python
from trading_platform.data.provider import DataProvider

class DataProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the data source."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    async def get_historical_bars(self, symbol, start, end, timeframe="1min") -> list[Bar]:
        """Override if provider supports historical data."""
        return []

    async def stream_bars(self, symbols) -> AsyncIterator[Bar]:
        """Override for live bar streaming."""
        return; yield

    async def stream_quotes(self, symbols) -> AsyncIterator[QuoteTick]:
        """Override for live quote streaming."""
        return; yield

    async def stream_trades(self, symbols) -> AsyncIterator[TradeTick]:
        """Override for live trade streaming."""
        return; yield
```

---

## DataManager

`trading_platform.data.manager.DataManager`

The DataManager orchestrates all data providers and publishes data to the EventBus.

```python
from trading_platform.core.events import EventBus
from trading_platform.data.manager import DataManager
from trading_platform.data.config import DataConfig

bus = EventBus()
config = DataConfig(csv_directory="/data/csvs")
dm = DataManager(bus, config)

# Register providers
dm.register_provider(my_provider)

# Start all providers
await dm.start()

# Programmatic ingestion
await dm.publish_bar({"symbol": "AAPL", "open": 185.0, ...})
await dm.publish_quote({"symbol": "AAPL", "bid_price": 185.0, ...})
await dm.publish_trade({"symbol": "AAPL", "price": 185.25, ...})

# Check status
dm.get_provider_status()   # [{"name": "csv:/data", "connected": true}]
dm.get_ingestion_stats()   # {"bars_received": 500, "quotes_received": 0, ...}

# Stop all providers
await dm.stop()
```

---

## CsvBarProvider

`trading_platform.data.file_provider.CsvBarProvider`

Loads historical bars from CSV files or directories.

**Expected CSV format:**

```csv
timestamp,symbol,open,high,low,close,volume
2024-01-15T09:30:00,AAPL,185.50,186.20,185.30,186.00,125000
2024-01-15T09:31:00,AAPL,186.00,186.50,185.80,186.30,80000
```

**Usage:**

```python
from trading_platform.data.file_provider import CsvBarProvider

# Single file
provider = CsvBarProvider("/data/bars.csv")

# Directory (loads all *.csv files)
provider = CsvBarProvider("/data/csv_dir/")

# With replay speed (2x real-time)
provider = CsvBarProvider("/data/bars.csv", replay_speed=2.0)

await provider.connect()

# Stream bars
async for bar in provider.stream_bars([]):
    print(bar.symbol, bar.close)

# Historical query
bars = await provider.get_historical_bars("AAPL", start, end)
```

---




```bash
```

```python

await provider.connect()
```

---

## REST & WebSocket Ingestion

The platform exposes endpoints for external data sources to push data in real time. These are automatically mounted when `data_manager` is provided to `create_app()`.

### REST Endpoints

**POST /api/data/bars** — Ingest bar data (single or batch):

```bash
# Single bar
curl -X POST http://localhost:8080/api/data/bars \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","open":185.0,"high":186.0,"low":184.5,"close":185.5,"volume":10000,"timestamp":"2024-01-15T09:30:00"}'

# Batch
curl -X POST http://localhost:8080/api/data/bars \
  -H "Content-Type: application/json" \
  -d '[{"symbol":"AAPL",...}, {"symbol":"MSFT",...}]'
```

**POST /api/data/quotes** — Ingest quote data:

```bash
curl -X POST http://localhost:8080/api/data/quotes \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","bid_price":185.0,"bid_size":100,"ask_price":185.5,"ask_size":200,"timestamp":"2024-01-15T09:30:00"}'
```

**POST /api/data/trades** — Ingest trade data:

```bash
curl -X POST http://localhost:8080/api/data/trades \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","price":185.25,"size":100,"timestamp":"2024-01-15T09:30:00"}'
```

**GET /api/data/status** — Ingestion statistics:

```json
{"bars_received": 500, "quotes_received": 1000, "trades_received": 200, "providers": 1}
```

**GET /api/data/providers** — Provider status:

```json
{"providers": [{"name": "csv:/data/bars.csv", "connected": true}]}
```

### WebSocket Ingestion

Connect to `ws://localhost:8080/ws/data` for streaming ingestion:

```python
import websockets, json, asyncio

async def stream_data():
    async with websockets.connect("ws://localhost:8080/ws/data") as ws:
        # Send a bar
        await ws.send(json.dumps({
            "type": "bar",
            "data": {
                "symbol": "AAPL", "open": 185.0, "high": 186.0,
                "low": 184.5, "close": 185.5, "volume": 10000,
                "timestamp": "2024-01-15T09:30:00"
            }
        }))
        resp = await ws.recv()  # {"status": "ok", "type": "bar"}

        # Send a quote
        await ws.send(json.dumps({
            "type": "quote",
            "data": {
                "symbol": "AAPL", "bid_price": 185.0, "bid_size": 100,
                "ask_price": 185.5, "ask_size": 200,
                "timestamp": "2024-01-15T09:30:00"
            }
        }))

        # Send a trade
        await ws.send(json.dumps({
            "type": "trade",
            "data": {
                "symbol": "AAPL", "price": 185.25, "size": 100,
                "timestamp": "2024-01-15T09:30:00"
            }
        }))
```

---

## Writing Custom Providers

Implement the `DataProvider` ABC to bring any data source into the platform:

```python
from collections.abc import AsyncIterator
from trading_platform.core.models import Bar, QuoteTick
from trading_platform.data.provider import DataProvider

class MyExchangeProvider(DataProvider):
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._connected = False
        self._ws = None

    @property
    def name(self) -> str:
        return "my-exchange"

    async def connect(self) -> None:
        self._ws = await my_exchange_sdk.connect(self._api_key)
        self._connected = True

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        async for raw in self._ws.bars():
            yield Bar(
                symbol=raw["sym"],
                open=raw["o"], high=raw["h"],
                low=raw["l"], close=raw["c"],
                volume=raw["v"],
                timestamp=raw["t"],
            )

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[QuoteTick]:
        async for raw in self._ws.quotes():
            yield QuoteTick(
                symbol=raw["sym"],
                bid_price=raw["bp"], bid_size=raw["bs"],
                ask_price=raw["ap"], ask_size=raw["as"],
                timestamp=raw["t"],
            )
```

Register it with the DataManager:

```python
provider = MyExchangeProvider(api_key="...")
data_manager.register_provider(provider)
await data_manager.start()
```

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

## ExecAdapter ABC

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

---

## Crypto Execution Adapter

`trading_platform.adapters.crypto.adapter.CryptoExecAdapter`

The crypto adapter enables cryptocurrency trading via Public.com's crypto endpoints, using the same `publicdotcom-py` SDK.

**Configuration:**
```python
from trading_platform.adapters.crypto.config import CryptoConfig
from trading_platform.adapters.crypto.adapter import CryptoExecAdapter

config = CryptoConfig(
    api_secret="your_api_secret",
    account_id="your_account_id",
    trading_pairs=["BTC-USD", "ETH-USD"],
)
adapter = CryptoExecAdapter(config, event_bus)
await adapter.connect()
```

**Fractional Quantities:**
Crypto supports fractional quantities (e.g., 0.005 BTC). The Order model's `quantity` field uses `Decimal` to support this.

**Symbol Format:**
Crypto uses pair format: "BTC-USD", "ETH-USD", "SOL-USD".

**24/7 Trading:**
Crypto markets never close. The adapter operates continuously without market-hours restrictions.

**Order Types:**
Market and limit orders are supported. Stop orders depend on Public.com's crypto API support.

**Example:**
```python
from trading_platform.core.models import Order
from trading_platform.core.enums import OrderSide, OrderType, AssetClass

order = Order(
    symbol="BTC-USD",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=Decimal("0.005"),
    limit_price=65000.00,
    asset_class=AssetClass.CRYPTO,
)
result = await adapter.submit_order(order)
```

---

## Options Execution Adapter

`trading_platform.adapters.options.adapter.OptionsExecAdapter`

The options adapter handles single-leg and multi-leg options orders via Public.com.

**Configuration:**
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

**Single-Leg Order:**
```python
from trading_platform.core.enums import ContractType

order = Order(
    symbol="AAPL250321C00150000",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=Decimal("1"),
    limit_price=5.00,
    asset_class=AssetClass.OPTION,
    contract_type=ContractType.CALL,
    strike_price=Decimal("150"),
    expiration_date=date(2025, 3, 21),
    underlying_symbol="AAPL",
)
result = await adapter.submit_option_order(order)
```

**Multi-Leg Order:**
```python
from trading_platform.core.models import MultiLegOrder

multileg = MultiLegOrder(
    legs=[long_leg, short_leg],
    strategy_type="VERTICAL_SPREAD",
    net_debit_or_credit=Decimal("2.50"),
)
result = await adapter.submit_multileg_order(multileg)
```

**Additional Methods:**
- `get_option_positions()` — Current options positions
- `get_option_chain(underlying)` — Available options for a symbol
- `get_option_expirations(underlying)` — Available expiration dates
- `preflight_option_order(order)` — Cost estimation

---

## Order Router

`trading_platform.core.order_router.OrderRouter`

The OrderRouter dispatches orders to the correct execution adapter based on asset class.

```python
from trading_platform.core.order_router import OrderRouter
from trading_platform.core.enums import AssetClass

router = OrderRouter()
router.register(AssetClass.EQUITY, equity_adapter)
router.register(AssetClass.OPTION, options_adapter)
router.register(AssetClass.CRYPTO, crypto_adapter)

# Orders are routed by their asset_class field
await router.submit_order(equity_order)   # → equity_adapter
await router.submit_order(crypto_order)   # → crypto_adapter
await router.submit_multileg_order(spread) # → options_adapter
```
