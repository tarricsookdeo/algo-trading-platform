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
```

---

## Data

### DataProvider (ABC)

`trading_platform.data.provider.DataProvider`

```python
class DataProvider(ABC):
    name: str  # abstract property
    is_connected: bool  # abstract property

    async def connect(self) -> None  # abstract
    async def disconnect(self) -> None  # abstract
    async def get_historical_bars(self, symbol: str, start: datetime, end: datetime, timeframe: str = "1min") -> list[Bar]
    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[Bar]
    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[QuoteTick]
    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[TradeTick]
```

### DataManager

`trading_platform.data.manager.DataManager`

```python
class DataManager:
    bars_received: int
    quotes_received: int
    trades_received: int

    def register_provider(self, provider: DataProvider) -> None
    async def start(self) -> None
    async def stop(self) -> None
    def get_provider_status(self) -> list[dict[str, Any]]
    def get_ingestion_stats(self) -> dict[str, Any]
    async def publish_bar(self, bar_data: dict[str, Any]) -> None
    async def publish_quote(self, quote_data: dict[str, Any]) -> None
    async def publish_trade(self, trade_data: dict[str, Any]) -> None
```

### DataConfig

`trading_platform.data.config.DataConfig`

```python
class DataConfig(BaseModel):
    ingestion_enabled: bool = True
    csv_directory: str = ""
    replay_speed: float = 0.0
    max_bars_per_request: int = 10000
```

### CsvBarProvider

`trading_platform.data.file_provider.CsvBarProvider`

```python
class CsvBarProvider(DataProvider):
    def __init__(self, file_path: str, replay_speed: float = 0.0)
    # Implements all DataProvider methods
    # Loads CSV on connect(), supports directory globbing
```

---

## Adapters

### ExecAdapter (ABC)

`trading_platform.adapters.base.ExecAdapter`

```python
class ExecAdapter(ABC):
    async def connect(self) -> None  # abstract
    async def disconnect(self) -> None  # abstract
    async def submit_order(self, order: Order) -> Any  # abstract
    async def cancel_order(self, order_id: str) -> Any  # abstract
    async def get_positions(self) -> list[Any]  # abstract
    async def get_account(self) -> Any  # abstract
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

### CryptoExecAdapter

`trading_platform.adapters.crypto.adapter.CryptoExecAdapter`

```python
class CryptoExecAdapter(ExecAdapter):
    def __init__(self, config: CryptoConfig, event_bus: EventBus) -> None

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def submit_order(self, order: Order) -> Any
    async def cancel_order(self, order_id: str) -> Any
    async def get_positions(self) -> list[Position]
    async def get_account(self) -> dict[str, Any]
    async def sync_portfolio(self) -> None
```

Supports 24/7 trading with no market-hours checks. Handles fractional quantities via `Decimal`. Runs a background portfolio refresh loop every `portfolio_refresh` seconds.

### CryptoClient

`trading_platform.adapters.crypto.client.CryptoClient`

```python
class CryptoClient:
    raw: AsyncPublicApiClient  # property

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def place_crypto_order(self, **kwargs: Any) -> Any
    async def cancel_crypto_order(self, order_id: str) -> None
    async def get_crypto_portfolio(self) -> Any
```

### CryptoConfig

`trading_platform.adapters.crypto.config.CryptoConfig`

```python
@dataclass
class CryptoConfig:
    api_secret: str = ""
    account_id: str = ""
    trading_pairs: list[str] = ["BTC-USD", "ETH-USD"]
    poll_interval: float = 2.0
    portfolio_refresh: float = 30.0
    token_validity_minutes: int = 15
```

### OptionsExecAdapter

`trading_platform.adapters.options.adapter.OptionsExecAdapter`

```python
class OptionsExecAdapter(ExecAdapter):
    def __init__(self, config: OptionsConfig, event_bus: EventBus) -> None

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def submit_order(self, order: Order) -> Any
    async def submit_option_order(self, order: Order) -> Any
    async def submit_multileg_order(self, multileg: MultiLegOrder) -> Any
    async def cancel_order(self, order_id: str) -> Any
    async def cancel_option_order(self, order_id: str) -> Any
    async def get_positions(self) -> list[Position]
    async def get_option_positions(self) -> list[Position]
    async def get_account(self) -> dict[str, Any]
    async def preflight_option_order(self, order: Order) -> Any
    async def get_option_chain(self, underlying: str) -> Any
    async def get_option_expirations(self, underlying: str) -> Any
    async def sync_portfolio(self) -> None
```

Supports single-leg and multi-leg option orders. Runs a background portfolio refresh loop. Maps platform `OrderSide`/`OrderType` enums to SDK equivalents.

### OptionsClient

`trading_platform.adapters.options.client.OptionsClient`

```python
class OptionsClient:
    raw: AsyncPublicApiClient  # property

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def place_option_order(self, request: OrderRequest, account_id: str | None = None) -> Any
    async def place_multileg_order(self, request: MultilegOrderRequest, account_id: str | None = None) -> Any
    async def cancel_order(self, order_id: str, account_id: str | None = None) -> None
    async def get_option_portfolio(self, account_id: str | None = None) -> Any
    async def perform_preflight(self, request: PreflightRequest, account_id: str | None = None) -> Any
    async def perform_multileg_preflight(self, request: PreflightMultiLegRequest, account_id: str | None = None) -> Any
    async def get_option_chain(self, underlying: str, account_id: str | None = None) -> Any
    async def get_option_expirations(self, underlying: str, account_id: str | None = None) -> Any
```

### OptionsConfig

`trading_platform.adapters.options.config.OptionsConfig`

```python
@dataclass
class OptionsConfig:
    api_secret: str = ""
    account_id: str = ""
    poll_interval: float = 2.0
    portfolio_refresh: float = 30.0
    token_validity_minutes: int = 15
```

### OrderRouter

`trading_platform.core.order_router.OrderRouter`

```python
class OrderRouter(ExecAdapter):
    def __init__(self) -> None

    def register(self, asset_class: AssetClass, adapter: ExecAdapter) -> None
    def get_adapter(self, asset_class: AssetClass) -> ExecAdapter | None
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def submit_order(self, order: Order) -> Any
    async def cancel_order(self, order_id: str) -> Any
    async def get_positions(self) -> list[Any]
    async def get_account(self) -> Any

    # Options-specific routing
    async def submit_multileg_order(self, multileg: MultiLegOrder) -> Any
    async def cancel_option_order(self, order_id: str) -> Any
    async def get_option_positions(self) -> list[Any]
    async def preflight_option_order(self, order: Order) -> Any
    async def get_option_chain(self, underlying: str) -> Any
    async def get_option_expirations(self, underlying: str) -> Any
```

Routes orders to asset-class-specific execution adapters by `order.asset_class`. Implements `ExecAdapter` so it can be used as a drop-in replacement. `get_positions()` and `get_account()` aggregate results from all registered adapters. `cancel_order()` tries all adapters.

---

## Bracket Orders

### BracketOrderManager

`trading_platform.bracket.manager.BracketOrderManager`

```python
class BracketOrderManager:
    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None)

    async def submit_bracket_order(
        self,
        symbol: str,
        quantity: int,
        entry_type: OrderType,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        entry_limit_price: Decimal | None = None,
    ) -> BracketOrder

    def get_bracket(self, bracket_id: str) -> BracketOrder | None
    def get_active_brackets(self) -> list[BracketOrder]
    def get_all_brackets(self) -> list[BracketOrder]
    async def cancel_bracket(self, bracket_id: str) -> bool
    async def wire_events(self) -> None
    async def unwire_events(self) -> None
```

### BracketOrder

`trading_platform.bracket.models.BracketOrder`

```python
class BracketOrder(BaseModel):
    bracket_id: str
    symbol: str
    quantity: int
    entry_type: OrderType
    entry_limit_price: Decimal | None = None
    stop_loss_price: Decimal
    take_profit_price: Decimal
    state: BracketState = BracketState.PENDING_ENTRY
    entry_order_id: str | None = None
    stop_loss_order_id: str | None = None
    take_profit_order_id: str | None = None
    entry_fill_price: Decimal | None = None
    exit_fill_price: Decimal | None = None
    created_at: datetime
    entry_filled_at: datetime | None = None
    completed_at: datetime | None = None
```

### BracketState

`trading_platform.bracket.enums.BracketState`

```python
class BracketState(StrEnum):
    PENDING_ENTRY = "pending_entry"
    ENTRY_PLACED = "entry_placed"
    ENTRY_FILLED = "entry_filled"
    STOP_LOSS_PLACED = "stop_loss_placed"
    MONITORING = "monitoring"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    TAKE_PROFIT_FILLED = "take_profit_filled"
    STOPPED_OUT = "stopped_out"
    CANCELED = "canceled"
    ENTRY_REJECTED = "entry_rejected"
    ERROR = "error"

TERMINAL_STATES = frozenset({
    BracketState.TAKE_PROFIT_FILLED,
    BracketState.STOPPED_OUT,
    BracketState.CANCELED,
    BracketState.ENTRY_REJECTED,
    BracketState.ERROR,
})
```

### BracketChannel

`trading_platform.bracket.enums.BracketChannel`

```python
class BracketChannel(StrEnum):
    BRACKET_ENTRY_FILLED = "bracket.entry.filled"
    BRACKET_STOP_PLACED = "bracket.stop.placed"
    BRACKET_STOPPED_OUT = "bracket.stopped_out"
    BRACKET_TAKE_PROFIT_TRIGGERED = "bracket.take_profit.triggered"
    BRACKET_TAKE_PROFIT_FILLED = "bracket.take_profit.filled"
    BRACKET_CANCELED = "bracket.canceled"
    BRACKET_ERROR = "bracket.error"
    BRACKET_STATE_CHANGE = "bracket.state_change"
```

---

## Options

### OptionsStrategyBuilder

`trading_platform.options.strategy_builder.OptionsStrategyBuilder`

```python
class OptionsStrategyBuilder:
    def __init__(self) -> None

    def build_vertical_spread(self, params: VerticalSpreadParams) -> MultiLegOrder
    def build_iron_condor(self, params: IronCondorParams) -> MultiLegOrder
    def build_straddle(self, params: StraddleParams) -> MultiLegOrder
    def build_strangle(self, params: StrangleParams) -> MultiLegOrder
    def build_butterfly_spread(self, params: ButterflySpreadParams) -> MultiLegOrder
    def build_calendar_spread(self, params: CalendarSpreadParams) -> MultiLegOrder
    async def build_and_submit(self, strategy_params: Any, order_router: Any) -> MultiLegOrder
```

Each `build_*` method validates parameters via `StrategyValidator`, constructs a `MultiLegOrder` with the correct legs, and returns it. `build_and_submit` builds, validates, and submits in one call.

### StrategyValidator

`trading_platform.options.validator.StrategyValidator`

```python
class StrategyValidator:
    def validate_vertical_spread(self, params: VerticalSpreadParams) -> StrategyAnalysis
    def validate_iron_condor(self, params: IronCondorParams) -> StrategyAnalysis
    def validate_straddle(self, params: StraddleParams) -> StrategyAnalysis
    def validate_strangle(self, params: StrangleParams) -> StrategyAnalysis
    def validate_butterfly_spread(self, params: ButterflySpreadParams) -> StrategyAnalysis
    def validate_calendar_spread(self, params: CalendarSpreadParams) -> StrategyAnalysis
    def validate_multileg_order(self, order: MultiLegOrder) -> StrategyAnalysis
```

Each method validates parameters and computes max profit, max loss, and breakeven prices. Returns a `StrategyAnalysis` with `is_valid` and any validation errors.

### StrategyValidationError

`trading_platform.options.validator.StrategyValidationError`

```python
class StrategyValidationError(Exception):
    errors: list[str]

    def __init__(self, errors: list[str]) -> None
```

### Strategy Parameter Dataclasses

`trading_platform.options.strategies`

All are `@dataclass(frozen=True)`:

```python
class VerticalSpreadParams:
    underlying: str
    expiration: date
    long_strike: Decimal
    short_strike: Decimal
    contract_type: ContractType
    quantity: Decimal = Decimal("1")

class IronCondorParams:
    underlying: str
    expiration: date
    put_long_strike: Decimal
    put_short_strike: Decimal
    call_short_strike: Decimal
    call_long_strike: Decimal
    quantity: Decimal = Decimal("1")

class StraddleParams:
    underlying: str
    expiration: date
    strike: Decimal
    quantity: Decimal = Decimal("1")
    side: str = "long"

class StrangleParams:
    underlying: str
    expiration: date
    put_strike: Decimal
    call_strike: Decimal
    quantity: Decimal = Decimal("1")
    side: str = "long"

class ButterflySpreadParams:
    underlying: str
    expiration: date
    lower_strike: Decimal
    middle_strike: Decimal
    upper_strike: Decimal
    contract_type: ContractType
    quantity: Decimal = Decimal("1")

class CalendarSpreadParams:
    underlying: str
    expiration_near: date
    expiration_far: date
    strike: Decimal
    contract_type: ContractType
    quantity: Decimal = Decimal("1")
```

### StrategyAnalysis

`trading_platform.options.strategies.StrategyAnalysis`

```python
@dataclass
class StrategyAnalysis:
    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    breakevens: list[Decimal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    is_valid: bool  # property — True when len(errors) == 0
```

### GreeksProvider

`trading_platform.options.greeks.GreeksProvider`

```python
class GreeksProvider:
    def __init__(self, client: Any, refresh_interval: float = 30.0)

    async def get_greeks(self, option_symbol: str) -> GreeksData
    async def get_portfolio_greeks(self, positions: list[Any]) -> AggregatedGreeks
    def invalidate(self, option_symbol: str | None = None) -> None
```

Fetches and caches option greeks with a TTL. `get_portfolio_greeks` aggregates greeks across all option positions. `invalidate` clears the cache for a single symbol or all symbols.

### GreeksData

`trading_platform.options.greeks.GreeksData`

```python
@dataclass(frozen=True)
class GreeksData:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    implied_volatility: float = 0.0
    timestamp: float = 0.0
```

### AggregatedGreeks

`trading_platform.options.greeks.AggregatedGreeks`

```python
@dataclass(frozen=True)
class AggregatedGreeks:
    total_delta: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0
    position_count: int = 0
```

### ExpirationManager

`trading_platform.options.expiration.ExpirationManager`

```python
class ExpirationManager:
    def __init__(
        self,
        config: ExpirationConfig,
        event_bus: EventBus,
        exec_adapter: ExecAdapter | None = None,
        strategy_builder: OptionsStrategyBuilder | None = None,
    )

    async def start(self) -> None
    async def stop(self) -> None
    def set_positions(self, positions: list[OptionsPosition]) -> None
    async def check_expirations(self, today: date | None = None) -> None
```

Monitors DTE for tracked option positions. Auto-closes positions at `auto_close_dte`, publishes alerts at `alert_dte`, and optionally rolls positions to `roll_target_dte` when `roll_enabled` is set.

### ExpirationConfig

`trading_platform.options.expiration.ExpirationConfig`

```python
@dataclass
class ExpirationConfig:
    auto_close_dte: int = 1
    alert_dte: int = 7
    roll_enabled: bool = False
    roll_target_dte: int = 30
    check_interval_seconds: float = 60.0
```

### OptionsPosition

`trading_platform.options.expiration.OptionsPosition`

```python
@dataclass
class OptionsPosition:
    symbol: str
    underlying: str
    quantity: float
    contract_type: ContractType
    strike_price: float
    expiration_date: date
    strategy_type: str = ""
```

---

## Trailing Stops

### TrailingStopManager

`trading_platform.orders.trailing_stop.TrailingStopManager`

```python
class TrailingStopManager:
    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None)

    async def create_trailing_stop(
        self,
        symbol: str,
        quantity: Decimal,
        current_price: Decimal,
        trail_amount: Decimal | None = None,
        trail_percent: Decimal | None = None,
    ) -> TrailingStop

    def get_trailing_stop(self, ts_id: str) -> TrailingStop | None
    def get_active_trailing_stops(self) -> list[TrailingStop]
    async def cancel_trailing_stop(self, ts_id: str) -> bool
    async def wire_events(self) -> None
    async def unwire_events(self) -> None
```

Creates ratcheting stop-loss orders that follow price upward. Provide either `trail_amount` (absolute dollar amount) or `trail_percent` (e.g., `Decimal("0.05")` for 5%). Monitors quote events and cancels/replaces the stop order when a new high is reached.

### TrailingStop

`trading_platform.orders.trailing_stop.TrailingStop`

```python
@dataclass
class TrailingStop:
    trailing_stop_id: str
    symbol: str
    quantity: Decimal
    trail_amount: Decimal | None
    trail_percent: Decimal | None
    current_stop_price: Decimal
    highest_price: Decimal
    stop_order_id: str | None
    state: TrailingStopState
    exit_fill_price: Decimal | None
    created_at: datetime
    completed_at: datetime | None
```

### TrailingStopState

`trading_platform.orders.trailing_stop.TrailingStopState`

```python
class TrailingStopState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"
```

### TrailingStopChannel

`trading_platform.orders.trailing_stop.TrailingStopChannel`

```python
class TrailingStopChannel(StrEnum):
    TRAILING_STOP_PLACED = "trailing_stop.placed"
    TRAILING_STOP_UPDATED = "trailing_stop.updated"
    TRAILING_STOP_COMPLETED = "trailing_stop.completed"
    TRAILING_STOP_CANCELED = "trailing_stop.canceled"
    TRAILING_STOP_ERROR = "trailing_stop.error"
    TRAILING_STOP_STATE_CHANGE = "trailing_stop.state_change"
```

---

## Scaled Orders

### ScaledOrderManager

`trading_platform.orders.scaled.ScaledOrderManager`

```python
class ScaledOrderManager:
    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None)

    async def create_scaled_exit(
        self,
        symbol: str,
        total_quantity: Decimal,
        take_profit_levels: list[tuple[Decimal, Decimal]],
        stop_loss_price: Decimal,
    ) -> ScaledExitOrder

    async def create_scaled_entry(
        self,
        symbol: str,
        total_quantity: Decimal,
        entry_levels: list[tuple[Decimal, Decimal]],
        stop_loss_price: Decimal,
    ) -> ScaledEntryOrder

    def get_scaled_exit(self, scaled_id: str) -> ScaledExitOrder | None
    def get_scaled_entry(self, scaled_id: str) -> ScaledEntryOrder | None
    async def wire_events(self) -> None
    async def unwire_events(self) -> None
```

Multi-tranche entries and exits with proportional quantity allocation. `take_profit_levels` and `entry_levels` are lists of `(price, quantity)` tuples. As tranches fill, the stop-loss is adjusted proportionally.

### ScaledExitOrder

`trading_platform.orders.scaled.ScaledExitOrder`

```python
@dataclass
class ScaledExitOrder:
    scaled_id: str
    symbol: str
    total_quantity: Decimal
    tranches: list[Tranche]
    stop_loss_price: Decimal
    stop_order_id: str | None
    remaining_quantity: Decimal
    state: ScaledOrderState
    created_at: datetime
    completed_at: datetime | None
```

### ScaledEntryOrder

`trading_platform.orders.scaled.ScaledEntryOrder`

```python
@dataclass
class ScaledEntryOrder:
    scaled_id: str
    symbol: str
    total_quantity: Decimal
    tranches: list[Tranche]
    stop_loss_price: Decimal
    stop_order_id: str | None
    filled_quantity: Decimal
    state: ScaledOrderState
    created_at: datetime
    completed_at: datetime | None
```

### Tranche

`trading_platform.orders.scaled.Tranche`

```python
@dataclass
class Tranche:
    price: Decimal
    quantity: Decimal
    filled: bool = False
    order_id: str | None = None
```

### ScaledOrderState

`trading_platform.orders.scaled.ScaledOrderState`

```python
class ScaledOrderState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"
```

### ScaledOrderChannel

`trading_platform.orders.scaled.ScaledOrderChannel`

```python
class ScaledOrderChannel(StrEnum):
    SCALED_EXIT_PLACED = "scaled.exit.placed"
    SCALED_EXIT_TRANCHE_FILLED = "scaled.exit.tranche_filled"
    SCALED_EXIT_COMPLETED = "scaled.exit.completed"
    SCALED_EXIT_STOPPED_OUT = "scaled.exit.stopped_out"
    SCALED_ENTRY_PLACED = "scaled.entry.placed"
    SCALED_ENTRY_TRANCHE_FILLED = "scaled.entry.tranche_filled"
    SCALED_ENTRY_COMPLETED = "scaled.entry.completed"
    SCALED_STOP_ADJUSTED = "scaled.stop_adjusted"
    SCALED_STATE_CHANGE = "scaled.state_change"
    SCALED_ERROR = "scaled.error"
    SCALED_CANCELED = "scaled.canceled"
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
    async def submit_bracket_order(
        self,
        symbol: str,
        quantity: int,
        entry_type: OrderType,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        entry_limit_price: Decimal | None = None,
    ) -> BracketOrder | None
    async def cancel_bracket_order(self, bracket_id: str) -> bool
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

### GreeksRiskConfig

`trading_platform.risk.greeks_checks.GreeksRiskConfig`

```python
@dataclass
class GreeksRiskConfig:
    max_portfolio_delta: float | None = None
    max_portfolio_gamma: float | None = None
    max_daily_theta: float | None = None
    max_portfolio_vega: float | None = None
    max_position_delta: float | None = None
    max_position_gamma: float | None = None
    max_position_vega: float | None = None
    greeks_refresh_interval_seconds: float = 30.0
```

### Greeks Risk Check Functions

`trading_platform.risk.greeks_checks`

All are async and return `tuple[bool, str]` — `(passed, reason)`:

```python
async def check_portfolio_delta(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_portfolio_gamma(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_theta_decay(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_vega_exposure(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_single_position_greeks(provider: GreeksProvider, order: Order, config: GreeksRiskConfig) -> tuple[bool, str]
```

`check_portfolio_delta/gamma/vega` compare aggregated portfolio greeks against the configured limits. `check_theta_decay` ensures daily theta does not exceed `max_daily_theta`. `check_single_position_greeks` checks per-position delta, gamma, and vega limits for a new order.

---

## Dashboard

### create_app

`trading_platform.dashboard.app.create_app`

```python
def create_app(
    event_bus: EventBus,
    data_manager: Any = None,
    exec_adapter: Any = None,
    strategy_manager: Any = None,
    risk_manager: Any = None,
    trailing_stop_manager: Any = None,
    scaled_order_manager: Any = None,
    bracket_order_manager: Any = None,
    greeks_provider: Any = None,
    expiration_manager: Any = None,
    options_strategy_builder: Any = None,
) -> tuple[FastAPI, DashboardWSManager]
```

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/status` | System status, event bus stats, provider status |
| `GET` | `/api/portfolio` | Positions and account info |
| `GET` | `/api/orders` | Tracked orders |
| `POST` | `/api/orders/{order_id}/cancel` | Cancel an order |
| `GET` | `/api/strategies` | All registered strategies |
| `POST` | `/api/strategies/{strategy_id}/start` | Start a strategy |
| `POST` | `/api/strategies/{strategy_id}/stop` | Stop a strategy |
| `GET` | `/api/risk` | Current risk state |
| `GET` | `/api/risk/violations` | Risk violation history |
| `GET` | `/api/pnl` | Daily and cumulative P&L |
| `GET` | `/api/trailing-stops` | Active trailing stops |
| `GET` | `/api/scaled-orders` | Scaled exits and entries |
| `GET` | `/api/brackets` | All bracket orders |
| `POST` | `/api/brackets/{bracket_id}/cancel` | Cancel a bracket order |
| `GET` | `/api/options/greeks/{option_symbol}` | Greeks for a single option |
| `GET` | `/api/options/portfolio-greeks` | Aggregated portfolio greeks |
| `GET` | `/api/options/expirations` | Tracked option positions with DTE |

### Data Ingestion Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/data/bars` | Ingest bar data |
| `POST` | `/api/data/quotes` | Ingest quote data |
| `POST` | `/api/data/trades` | Ingest trade data |
| `WS` | `/ws/data` | Stream data via WebSocket |

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
    data: DataSettings
    public_com: PublicComSettings
    crypto: CryptoSettings
    options: OptionsSettings
    trailing_stop: TrailingStopSettings
    expiration: ExpirationSettings
    dashboard: DashboardSettings
    platform: PlatformSettings
    risk: RiskSettings          # includes risk.greeks subsection
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
