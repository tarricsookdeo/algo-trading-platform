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
    quantity: Decimal = Decimal("0")
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    filled_avg_price: float = 0.0
    asset_class: AssetClass = AssetClass.STOCK
    contract_type: ContractType | None = None       # CALL or PUT (options only)
    strike_price: float | None = None               # options only
    expiration_date: date | None = None              # options only
    underlying_symbol: str | None = None             # options only
    option_symbol: str | None = None                 # OCC-style symbol (options only)
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

#### MultiLegOrder

```python
class MultiLegOrder(BaseModel):
    order_id: str = ""
    legs: list[Order] = []
    strategy_type: str = ""                         # e.g. "vertical_spread", "iron_condor"
    status: OrderStatus = OrderStatus.NEW
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
    EXPIRATION_WARNING = "options.expiration.warning"
    POSITION_AUTO_CLOSED = "options.position.auto_closed"
    POSITION_ROLLED = "options.position.rolled"

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
    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"

class ContractType(StrEnum):
    CALL = "call"
    PUT = "put"

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



```python
    def __init__(self, file_path: str, replay_speed: float = 0.0)
    # Implements all DataProvider methods
```

---

## Adapters

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

### OrderRouter

`trading_platform.core.order_router.OrderRouter`

```python
class OrderRouter(ExecAdapter):
    def register(self, asset_class: AssetClass, adapter: ExecAdapter) -> None
    def get_adapter(self, asset_class: AssetClass) -> ExecAdapter | None
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def submit_order(self, order: Order) -> Any  # routes by order.asset_class
    async def submit_multileg_order(self, multileg: MultiLegOrder) -> Any
    async def cancel_order(self, order_id: str) -> Any
    async def get_positions(self) -> list[Any]
    async def get_account(self) -> Any
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

### OptionsExecAdapter

`trading_platform.adapters.options.adapter.OptionsExecAdapter`

```python
class OptionsExecAdapter(ExecAdapter):
    def __init__(self, config: OptionsConfig, event_bus: EventBus) -> None
    async def submit_option_order(self, order: Order) -> Any
    async def submit_multileg_order(self, multileg: MultiLegOrder) -> Any
    async def cancel_option_order(self, order_id: str) -> Any
    async def get_option_positions(self) -> list[Position]
    async def preflight_option_order(self, order: Order) -> Any
    async def get_option_chain(self, underlying: str) -> Any
    async def get_option_expirations(self, underlying: str) -> Any
```

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

## Trailing Stops

### TrailingStopManager

`trading_platform.orders.trailing_stop.TrailingStopManager`

```python
class TrailingStopState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"

class TrailingStop:  # dataclass
    trailing_stop_id: str
    symbol: str
    quantity: Decimal
    trail_amount: Decimal
    trail_percent: Decimal
    current_stop_price: Decimal
    highest_price: Decimal
    stop_order_id: str | None
    state: TrailingStopState
    exit_fill_price: Decimal | None

class TrailingStopManager:
    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None) -> None

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

---

## Scaled Orders

### ScaledOrderManager

`trading_platform.orders.scaled.ScaledOrderManager`

```python
class ScaledOrderState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"

class Tranche:  # dataclass
    price: Decimal
    quantity: Decimal
    filled: bool = False
    order_id: str | None = None

class ScaledExitOrder:  # dataclass
    scaled_id: str
    symbol: str
    total_quantity: Decimal
    tranches: list[Tranche]
    stop_loss_price: Decimal
    remaining_quantity: Decimal
    state: ScaledOrderState

class ScaledEntryOrder:  # dataclass
    scaled_id: str
    symbol: str
    total_quantity: Decimal
    tranches: list[Tranche]
    stop_loss_price: Decimal
    filled_quantity: Decimal
    state: ScaledOrderState

class ScaledOrderManager:
    def __init__(self, event_bus: EventBus, exec_adapter: ExecAdapter | None = None) -> None

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

---

## Options

### OptionsStrategyBuilder

`trading_platform.options.strategy_builder.OptionsStrategyBuilder`

```python
class OptionsStrategyBuilder:
    def build_vertical_spread(self, params: VerticalSpreadParams) -> MultiLegOrder
    def build_iron_condor(self, params: IronCondorParams) -> MultiLegOrder
    def build_straddle(self, params: StraddleParams) -> MultiLegOrder
    def build_strangle(self, params: StrangleParams) -> MultiLegOrder
    def build_butterfly_spread(self, params: ButterflySpreadParams) -> MultiLegOrder
    def build_calendar_spread(self, params: CalendarSpreadParams) -> MultiLegOrder
    async def build_and_submit(self, strategy_params: Any, order_router: OrderRouter) -> MultiLegOrder
```

### Strategy Parameter Models

`trading_platform.options.strategies`

All frozen dataclasses:

- `VerticalSpreadParams` — long/short strike, expiration, contract type, quantity
- `IronCondorParams` — call/put spread strikes, expiration, quantity
- `StraddleParams` — strike, expiration, quantity
- `StrangleParams` — call/put strikes, expiration, quantity
- `ButterflySpreadParams` — lower/middle/upper strikes, expiration, contract type, quantity
- `CalendarSpreadParams` — strike, near/far expiration, contract type, quantity
- `StrategyAnalysis` — is_valid, max_profit, max_loss, breakeven points, warnings

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

### GreeksProvider

`trading_platform.options.greeks.GreeksProvider`

```python
class GreeksData:  # frozen dataclass
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    implied_volatility: float
    timestamp: float

class AggregatedGreeks:  # frozen dataclass
    total_delta: float
    total_gamma: float
    total_theta: float
    total_vega: float
    position_count: int

class GreeksProvider:
    def __init__(self, client: Any, refresh_interval: float = 30.0) -> None
    async def get_greeks(self, option_symbol: str) -> GreeksData
    async def get_portfolio_greeks(self, positions: list[Any]) -> AggregatedGreeks
    def invalidate(self, option_symbol: str | None = None) -> None
```

### ExpirationManager

`trading_platform.options.expiration.ExpirationManager`

```python
class ExpirationConfig:  # dataclass
    auto_close_dte: int = 1
    alert_dte: int = 7
    roll_enabled: bool = False
    roll_target_dte: int = 30
    check_interval_seconds: float = 60.0

class OptionsPosition:  # dataclass
    symbol: str
    underlying: str
    quantity: float
    contract_type: ContractType
    strike_price: float
    expiration_date: date
    strategy_type: str = ""

class ExpirationManager:
    def __init__(
        self,
        config: ExpirationConfig,
        event_bus: EventBus,
        exec_adapter: ExecAdapter | None = None,
        strategy_builder: OptionsStrategyBuilder | None = None,
    ) -> None

    async def start(self) -> None
    async def stop(self) -> None
    def set_positions(self, positions: list[OptionsPosition]) -> None
    async def check_expirations(self, today: date | None = None) -> None
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

### Greeks Risk Checks

`trading_platform.risk.greeks_checks`

```python
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

All return `tuple[bool, str]` -- `(passed, reason)`:

```python
async def check_portfolio_delta(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_portfolio_gamma(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_theta_decay(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_vega_exposure(provider: GreeksProvider, positions: list[Any], config: GreeksRiskConfig) -> tuple[bool, str]
async def check_single_position_greeks(provider: GreeksProvider, order: Order, config: GreeksRiskConfig) -> tuple[bool, str]
```

---

## Dashboard

### create_app

`trading_platform.dashboard.app.create_app`

```python
def create_app(
    event_bus: EventBus,
    data_manager: Any = None,
    exec_adapter: Any = None,
    order_router: Any = None,
    strategy_manager: Any = None,
    risk_manager: Any = None,
    greeks_provider: Any = None,
    expiration_manager: Any = None,
    trailing_stop_manager: Any = None,
    scaled_order_manager: Any = None,
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
    data: DataSettings
    public_com: PublicComSettings
    crypto: CryptoSettings            # exchange, api_key, api_secret, etc.
    options: OptionsSettings           # options adapter configuration
    dashboard: DashboardSettings
    platform: PlatformSettings
    risk: RiskSettings                 # includes risk.greeks (GreeksRiskConfig)
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
