# API Reference

Quick reference for all public classes, methods, and enums in the `trading_platform` package.

## Core

### EventBus

`trading_platform.core.events.EventBus`

```python
class EventBus:
    total_published: int
    channel_counts: dict[str, int]
    subscriber_count: int  # property

    async def publish(self, channel: str | Channel, event: Any) -> None
    async def subscribe(self, channel: str | Channel, callback: Callback) -> None
    async def unsubscribe(self, channel: str | Channel, callback: Callback) -> None
    def events_per_second(self) -> float
```

`Callback = Callable[[str, Any], Coroutine[Any, Any, None]]`

### Models

`trading_platform.core.models`

#### QuoteTick

```python
class QuoteTick(BaseModel):
    symbol: str
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float
    bid_exchange: str = ""
    ask_exchange: str = ""
    timestamp: datetime
    conditions: list[str] = []
```

#### TradeTick

```python
class TradeTick(BaseModel):
    symbol: str
    price: float
    size: float
    exchange: str = ""
    trade_id: str = ""
    conditions: list[str] = []
    timestamp: datetime
    tape: str = ""
```

#### Bar

```python
class Bar(BaseModel):
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    trade_count: int = 0
    timestamp: datetime
    bar_type: BarType = BarType.MINUTE
```

#### TradingStatus

```python
class TradingStatus(BaseModel):
    symbol: str
    status_code: str
    status_message: str
    reason_code: str = ""
    reason_message: str = ""
    timestamp: datetime
```

#### LULD

```python
class LULD(BaseModel):
    symbol: str
    limit_up: float
    limit_down: float
    indicator: str = ""
    timestamp: datetime
```

#### Instrument

```python
class Instrument(BaseModel):
    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.STOCK
    exchange: str = ""
    tradable: bool = True
    shortable: bool = False
    marginable: bool = False
    easy_to_borrow: bool = False
    strike: float | None = None
    expiry: datetime | None = None
    option_type: str | None = None
    underlying: str | None = None
```

#### Order

```python
class Order(BaseModel):
    order_id: str = ""
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    filled_avg_price: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

#### Fill

```python
class Fill(BaseModel):
    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    price: float = 0.0
    quantity: float = 0.0
    timestamp: datetime | None = None
```

#### Position

```python
class Position(BaseModel):
    symbol: str = ""
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    side: str = ""
```

#### SystemEvent

```python
class SystemEvent(BaseModel):
    component: str
    message: str
    level: str = "info"
    data: dict[str, Any] = {}
    timestamp: datetime | None = None
```

---

## Enums

`trading_platform.core.enums`

```python
class Channel(StrEnum):
    QUOTE = "quote"
    TRADE = "trade"
    BAR = "bar"
    STATUS = "status"
    ORDER = "order"
    FILL = "fill"
    POSITION = "position"
    SYSTEM = "system"
    ERROR = "error"

class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"

class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class OrderStatus(StrEnum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    PENDING_NEW = "pending_new"
    PENDING_CANCEL = "pending_cancel"
    EXPIRED = "expired"

class AssetClass(StrEnum):
    STOCK = "stock"
    OPTION = "option"
    CRYPTO = "crypto"

class BarType(StrEnum):
    MINUTE = "minute"
    DAILY = "daily"
    UPDATED = "updated"

class DataFeed(StrEnum):
    SIP = "sip"
    IEX = "iex"
    OPRA = "opra"
```

---

## Adapters

### AlpacaDataAdapter

`trading_platform.adapters.alpaca.adapter.AlpacaDataAdapter`

```python
class AlpacaDataAdapter(DataAdapter):
    stock_stream: AlpacaStockStream
    options_stream: AlpacaOptionsStream
    rest_client: AlpacaClient
    instrument_provider: AlpacaInstrumentProvider
    is_connected: bool  # property

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def subscribe_quotes(self, symbols: list[str]) -> None
    async def subscribe_trades(self, symbols: list[str]) -> None
    async def subscribe_bars(self, symbols: list[str]) -> None
    async def unsubscribe(self, symbols: list[str]) -> None
```

### AlpacaStockStream

`trading_platform.adapters.alpaca.stream.AlpacaStockStream`

```python
class AlpacaStockStream:
    is_connected: bool  # property
    messages_received: int
    last_message_time: float
    reconnect_count: int

    async def start(self) -> None
    async def stop(self) -> None
    async def subscribe(self, trades: list[str] | None, quotes: list[str] | None, bars: list[str] | None) -> None
    async def unsubscribe(self, symbols: list[str]) -> None
```

### AlpacaOptionsStream

`trading_platform.adapters.alpaca.stream.AlpacaOptionsStream`

```python
class AlpacaOptionsStream:
    MAX_QUOTE_SUBSCRIPTIONS = 1000
    is_connected: bool  # property
    messages_received: int
    last_message_time: float
    reconnect_count: int

    async def start(self) -> None
    async def stop(self) -> None
    async def subscribe(self, trades: list[str] | None, quotes: list[str] | None) -> None
    async def unsubscribe(self, symbols: list[str]) -> None
```

### AlpacaClient

`trading_platform.adapters.alpaca.client.AlpacaClient`

```python
class AlpacaClient:
    RATE_LIMIT = 10_000
    MAX_RETRIES = 5

    async def start(self) -> None
    async def close(self) -> None
    async def get_bars(self, symbol: str, timeframe: str = "1Min", start: str | datetime | None = None, end: str | datetime | None = None, limit: int = 1000, feed: str | None = None, adjustment: str = "raw") -> list[dict]
    async def get_trades(self, symbol: str, start: str | datetime | None = None, end: str | datetime | None = None, limit: int = 1000, feed: str | None = None) -> list[dict]
    async def get_quotes(self, symbol: str, start: str | datetime | None = None, end: str | datetime | None = None, limit: int = 1000, feed: str | None = None) -> list[dict]
    async def get_snapshot(self, symbol: str, feed: str | None = None) -> dict
    async def get_latest_trade(self, symbol: str, feed: str | None = None) -> dict
    async def get_latest_quote(self, symbol: str, feed: str | None = None) -> dict
```

### AlpacaInstrumentProvider

`trading_platform.adapters.alpaca.provider.AlpacaInstrumentProvider`

```python
class AlpacaInstrumentProvider:
    async def start(self) -> None
    async def close(self) -> None
    async def load_stock_instruments(self) -> int
    def get_instrument(self, symbol: str) -> Instrument | None
    def get_all_instruments(self) -> dict[str, Instrument]
    def search(self, query: str) -> list[Instrument]
```

### PublicComExecAdapter

`trading_platform.adapters.public_com.adapter.PublicComExecAdapter`

```python
class PublicComExecAdapter(ExecAdapter):
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def submit_order(self, order: Order) -> Any
    async def submit_multileg_order(self, request: MultilegOrderRequest) -> Any
    async def cancel_order(self, order_id: str) -> Any
    async def cancel_and_replace(self, request: CancelAndReplaceRequest) -> Any
    async def get_positions(self) -> list[Position]
    async def get_account(self) -> dict[str, Any]
    async def perform_preflight(self, order: Order) -> Any
    async def sync_portfolio(self) -> None
```

### PublicComClient

`trading_platform.adapters.public_com.client.PublicComClient`

```python
class PublicComClient:
    raw: AsyncPublicApiClient  # property

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def get_accounts(self) -> Any
    async def get_portfolio(self, account_id: str | None = None) -> Any
    async def get_quotes(self, instruments: list[OrderInstrument], account_id: str | None = None) -> Any
    async def place_order(self, request: OrderRequest, account_id: str | None = None) -> Any
    async def place_multileg_order(self, request: MultilegOrderRequest, account_id: str | None = None) -> Any
    async def get_order(self, order_id: str, account_id: str | None = None) -> Any
    async def cancel_order(self, order_id: str, account_id: str | None = None) -> None
    async def cancel_and_replace_order(self, request: CancelAndReplaceRequest, account_id: str | None = None) -> Any
    async def perform_preflight(self, request: PreflightRequest, account_id: str | None = None) -> Any
    async def perform_multileg_preflight(self, request: PreflightMultiLegRequest, account_id: str | None = None) -> Any
```

---

## Strategy

### Strategy (ABC)

`trading_platform.strategy.base.Strategy`

```python
class Strategy(ABC):
    name: str
    event_bus: EventBus
    config: dict[str, Any]
    context: Any  # StrategyContext, injected by StrategyManager
    is_active: bool

    async def on_start(self) -> None
    async def on_stop(self) -> None
    async def on_quote(self, quote: QuoteTick) -> None       # abstract
    async def on_trade(self, trade: TradeTick) -> None       # abstract
    async def on_bar(self, bar: Bar) -> None                 # abstract
    async def on_order_update(self, order_update: Any) -> None
    async def on_position_update(self, positions: list[Any]) -> None
    async def on_signal(self, signal: Any) -> None
```

### StrategyContext

`trading_platform.strategy.context.StrategyContext`

```python
class StrategyContext:
    strategy_id: str

    def update_quote(self, quote: QuoteTick) -> None
    def update_bar(self, bar: Bar) -> None
    def update_positions(self, positions: list[Position]) -> None
    def get_latest_quote(self, symbol: str) -> QuoteTick | None
    def get_latest_bar(self, symbol: str) -> Bar | None
    def get_positions(self) -> list[Position]
    async def submit_order(self, order: Order) -> Any
    async def cancel_order(self, order_id: str) -> Any
```

### StrategyManager

`trading_platform.strategy.manager.StrategyManager`

```python
class StrategyManager:
    def register(self, strategy: Strategy) -> None
    def deregister(self, strategy_id: str) -> None
    async def start_strategy(self, strategy_id: str) -> None
    async def stop_strategy(self, strategy_id: str) -> None
    async def start_all(self) -> None
    async def stop_all(self) -> None
    async def wire_events(self) -> None
    async def unwire_events(self) -> None
    def get_strategy_info(self) -> list[dict[str, Any]]
    def get_strategy_entry(self, strategy_id: str) -> StrategyEntry | None

    # Event dispatch (called by EventBus subscriptions)
    async def dispatch_quote(self, channel: str, event: Any) -> None
    async def dispatch_trade(self, channel: str, event: Any) -> None
    async def dispatch_bar(self, channel: str, event: Any) -> None
    async def dispatch_order_update(self, channel: str, event: Any) -> None
    async def dispatch_position_update(self, channel: str, event: Any) -> None
```

### StrategyState

```python
class StrategyState(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"
```

---

## Risk

### RiskManager

`trading_platform.risk.manager.RiskManager`

```python
class RiskManager:
    config: RiskConfig
    state: RiskState

    async def pre_trade_check(self, order: Order, positions: list[Position]) -> tuple[bool, str]
    async def post_trade_check(self) -> None
    async def update_portfolio_value(self, value: float) -> None
    async def update_daily_pnl(self, pnl: float) -> None
    def update_open_order_count(self, count: int) -> None
    async def reset_daily(self) -> None
    def get_risk_state(self) -> dict[str, Any]
    def get_violations(self) -> list[dict[str, Any]]
```

### RiskConfig

`trading_platform.risk.models.RiskConfig`

```python
class RiskConfig(BaseModel):
    max_position_size: float = 1000.0
    max_position_concentration: float = 0.10
    max_order_value: float = 50000.0
    daily_loss_limit: float = -5000.0
    max_open_orders: int = 20
    max_daily_trades: int = 100
    max_portfolio_drawdown: float = 0.15
    allowed_symbols: list[str] = []
    blocked_symbols: list[str] = []
```

### RiskState

`trading_platform.risk.models.RiskState`

```python
class RiskState(BaseModel):
    is_halted: bool = False
    halt_reason: str = ""
    daily_pnl: float = 0.0
    daily_trade_count: int = 0
    portfolio_peak: float = 0.0
    portfolio_value: float = 0.0
    open_order_count: int = 0
    violations: list[RiskViolation] = []
```

### RiskViolation

`trading_platform.risk.models.RiskViolation`

```python
class RiskViolation(BaseModel):
    check_name: str
    message: str
    order_id: str = ""
    symbol: str = ""
    timestamp: datetime | None = None
    data: dict[str, Any] = {}
```

### Risk Check Functions

`trading_platform.risk.checks`

All return `tuple[bool, str]` — `(passed, reason)`:

```python
def check_position_size(order: Order, positions: list[Position], config: RiskConfig) -> tuple[bool, str]
def check_position_concentration(order: Order, positions: list[Position], config: RiskConfig, portfolio_value: float) -> tuple[bool, str]
def check_order_value(order: Order, config: RiskConfig) -> tuple[bool, str]
def check_daily_loss(state: RiskState, config: RiskConfig) -> tuple[bool, str]
def check_max_open_orders(state: RiskState, config: RiskConfig) -> tuple[bool, str]
def check_symbol_allowed(order: Order, config: RiskConfig) -> tuple[bool, str]
def check_portfolio_drawdown(state: RiskState, config: RiskConfig) -> tuple[bool, str]
def check_daily_trade_count(state: RiskState, config: RiskConfig) -> tuple[bool, str]
```

---

## Dashboard

### create_app

`trading_platform.dashboard.app.create_app`

```python
def create_app(
    event_bus: EventBus,
    adapter: Any = None,
    exec_adapter: Any = None,
    strategy_manager: Any = None,
    risk_manager: Any = None,
) -> tuple[FastAPI, DashboardWSManager]
```

### DashboardWSManager

`trading_platform.dashboard.ws.DashboardWSManager`

```python
class DashboardWSManager:
    async def start(self) -> None
    async def stop(self) -> None
    async def connect(self, ws: WebSocket) -> None
    async def disconnect(self, ws: WebSocket) -> None
    async def broadcast(self, message: dict[str, Any]) -> None
```

---

## Configuration

### Settings

`trading_platform.core.config.Settings`

```python
class Settings:
    alpaca: AlpacaSettings
    public_com: PublicComSettings
    dashboard: DashboardSettings
    platform: PlatformSettings
    risk: RiskSettings
```

### Functions

```python
def load_toml(path: Path) -> dict[str, Any]
def load_settings(config_path: Path | None = None) -> Settings
```

### Logging

`trading_platform.core.logging`

```python
def setup_logging(level: str = "INFO", json_output: bool = False) -> None
def get_logger(component: str) -> structlog.stdlib.BoundLogger
```

### Clock

`trading_platform.core.clock`

```python
def now() -> datetime
def now_ns() -> int
```
