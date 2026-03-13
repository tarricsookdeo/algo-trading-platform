# Architecture Guide

## System Overview

The algo trading platform is a production-oriented, event-driven system built in Python. All components communicate through a central async event bus — there is no direct coupling between data ingestion, strategy logic, risk management, execution, or the monitoring dashboard.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                             Dashboard (FastAPI + WebSocket)                                    │
│   REST API: /api/status, /api/portfolio, /api/orders, /api/strategies                         │
│   WebSocket: /ws (quotes, trades, bars, metrics, portfolio, risk)                             │
│   Data Ingestion: POST /api/data/bars, /quotes, /trades; WS /ws/data                         │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│                                        Event Bus                                              │
│  Market: quote │ trade │ bar │ status       Strategy: signal │ lifecycle                      │
│  Exec: order.submitted │ .filled │ ...     Risk: check.* │ alert │ halt │ greeks.*           │
│  Bracket: bracket.entry.filled │ .stopped_out │ .take_profit.* │ ...                         │
│  Trailing: trailing_stop.placed │ .updated │ .completed │ .canceled                          │
│  Scaled: scaled.exit.placed │ .tranche_filled │ scaled.entry.placed │ ...                    │
│  Options: options.expiration.warning │ .position.auto_closed │ .position.rolled               │
│  System: system │ error                    Portfolio: portfolio │ account                      │
├────────────┬──────────────────────────────┬───────────────┬───────────────┬───────────────────┤
│ DataManager│        Order Router          │ Bracket Mgr   │ Strategy Mgr  │  Risk Manager     │
│ (BYOD)     │  ┌────────────────────────┐  │               │               │                   │
│            │  │ Routes by asset_class  │  │ Entry→SL→TP   │ ┌───────────┐ │  Pre-trade:       │
│┌──────────┐│  ├────────────────────────┤  │ SL rests live │ │ Strategy  │ │  6 checks         │
││ CSV/Parq ││  │ Equity Adapter         │  │ TP bid watch  │ │ ┌───────┐│ │  + Greeks checks  │
││ Providers││  │ (PublicComExecAdapter)  │  │               │ │ │Context││ │                   │
│├──────────┤│  ├────────────────────────┤  │ State machine:│ │ └───────┘│ │  Post-trade:      │
││ REST     ││  │ Crypto Adapter         │  │ PENDING →     │ │ on_bar() │ │  2 checks         │
││ Ingestion││  │ (CryptoExecAdapter)    │  │ MONITORING →  │ │ on_quote│ │                   │
│├──────────┤│  ├────────────────────────┤  │ STOPPED_OUT / │ └───────────┘ │  Halt/resume      │
││ WebSocket││  │ Options Adapter        │  │ TP_FILLED     │               │                   │
││ Ingestion││  │ (OptionsExecAdapter)   │  │               │               │                   │
│├──────────┤│  └────────────────────────┘  ├───────────────┤               │                   │
││ Custom   ││                              │ Trailing Stop │               │                   │
││ Providers││                              │ Manager       │               │                   │
│└──────────┘│                              ├───────────────┤               │                   │
│            │                              │ Scaled Order  │               │                   │
│            │                              │ Manager       │               │                   │
├────────────┴──────────────────────────────┴───────────────┴───────────────┴───────────────────┤
│                                    Options Layer                                              │
│  OptionsStrategyBuilder │ StrategyValidator │ GreeksProvider │ ExpirationManager              │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│                                    Core Domain                                                │
│  Models: QuoteTick, TradeTick, Bar, Order, MultiLegOrder, Position, Fill, Instrument         │
│  Config (Pydantic Settings) │ Logging (structlog) │ Clock │ Enums                            │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Event-Driven Design

Every component publishes and subscribes to events on named channels. This design provides:

- **Loose coupling** — Components don't import or reference each other directly
- **Extensibility** — New subscribers can be added without modifying publishers
- **Observability** — The dashboard subscribes to all events for real-time monitoring
- **Testability** — Components can be tested in isolation with a mock EventBus

### Event Flow: Data Ingestion → Dashboard

```
DataProvider.stream_bars()  ─┐
REST POST /api/data/bars     ├→ DataManager → publish(Channel.BAR, Bar)
WebSocket /ws/data           ─┘                    │
                                   ┌───────────────┤
                                   ▼                ▼
                           DashboardWSManager    StrategyManager
                           (broadcast to UI)     (dispatch to strategies)
```

### Event Flow: Strategy → Execution

```
Strategy.on_bar()
    │
    ▼
Strategy.on_signal(signal)
    │
    ├── publish("strategy.signal", {...})
    │
    ▼
StrategyContext.submit_order(order)
    │
    ├── RiskManager.pre_trade_check(order, positions)
    │       │
    │       ├── PASS → publish("risk.check.passed")
    │       └── FAIL → publish("risk.check.failed") → return None
    │
    ▼
PublicComExecAdapter.submit_order(order)
    │
    ├── publish("execution.order.submitted")
    │
    ▼
_track_order() (async polling)
    │
    ├── publish("execution.order.filled")
    ├── publish("execution.order.partially_filled")
    ├── publish("execution.order.cancelled")
    └── publish("execution.order.rejected")
```

### Event Flow: Bracket Order Lifecycle

```
StrategyContext.submit_bracket_order(symbol, qty, ...)
    │
    ▼
BracketOrderManager.submit_bracket_order()
    │
    ├── Validate params → create BracketOrder
    ├── Place entry order via ExecAdapter
    │       │
    │       ▼
    │   "execution.order.filled" (entry)
    │       │
    │       ├── Record entry fill price
    │       ├── publish("bracket.entry.filled")
    │       ├── Place stop-loss order (resting)
    │       ├── publish("bracket.stop.placed")
    │       └── Enter MONITORING state
    │
    │   ┌── "quote" events (bid price monitoring) ──┐
    │   │                                            │
    │   │  bid >= take_profit_price?                 │
    │   │      │ YES                                 │
    │   │      ├── publish("bracket.take_profit.triggered")
    │   │      ├── Cancel stop-loss order            │
    │   │      ├── Wait for "execution.order.cancelled" (stop)
    │   │      ├── Place market sell                 │
    │   │      └── "execution.order.filled" (sell)   │
    │   │          └── publish("bracket.take_profit.filled")
    │   │                                            │
    │   └── "execution.order.filled" (stop-loss) ───┘
    │       └── publish("bracket.stopped_out")
    │
    └── All state changes → publish("bracket.state_change")
```

### Event Flow: Trailing Stop Lifecycle

```
TrailingStopManager.create_trailing_stop(symbol, qty, price, trail_amount/trail_percent)
    │
    ▼
Place initial stop order via ExecAdapter
    │
    ├── publish("trailing_stop.placed", {trailing_stop_id, symbol, stop_price})
    │
    ▼
Monitor "quote" events for symbol
    │
    ├── price moves up → ratchet stop price higher
    │       │
    │       ├── cancel_and_replace stop order with new stop price
    │       └── publish("trailing_stop.updated", {trailing_stop_id, new_stop_price, highest_price})
    │
    ├── "execution.order.filled" (stop triggered)
    │       │
    │       └── publish("trailing_stop.completed", {trailing_stop_id, exit_fill_price})
    │
    └── cancel_trailing_stop(ts_id)
            │
            └── publish("trailing_stop.canceled", {trailing_stop_id})
```

**Channels:** `trailing_stop.placed`, `trailing_stop.updated`, `trailing_stop.completed`, `trailing_stop.canceled`

### Event Flow: Scaled Order Lifecycle

```
ScaledOrderManager.create_scaled_exit(symbol, qty, take_profit_levels, stop_loss_price)
    │
    ▼
Place limit sell orders for each exit tranche
    │
    ├── publish("scaled.exit.placed", {scaled_id, symbol, tranches})
    │
    ▼
Monitor "execution.order.filled" for tranche fills
    │
    ├── Tranche filled → adjust stop-loss for remaining quantity
    │       │
    │       └── publish("scaled.exit.tranche_filled", {scaled_id, tranche_price, remaining_qty})
    │
    └── All tranches filled or stopped out
            │
            └── publish("scaled.exit.completed", {scaled_id, total_filled})


ScaledOrderManager.create_scaled_entry(symbol, qty, entry_levels, stop_loss_price)
    │
    ▼
Place limit buy orders for each entry tranche
    │
    ├── publish("scaled.entry.placed", {scaled_id, symbol, tranches})
    │
    ▼
Monitor "execution.order.filled" for tranche fills
    │
    └── Tranche filled
            │
            └── publish("scaled.entry.tranche_filled", {scaled_id, tranche_price, filled_qty})
```

**Channels:** `scaled.exit.placed`, `scaled.exit.tranche_filled`, `scaled.exit.completed`, `scaled.entry.placed`, `scaled.entry.tranche_filled`

### Event Flow: Options Strategy Flow

```
OptionsStrategyBuilder.build_vertical_spread(params) / build_iron_condor(params) / ...
    │
    ▼
StrategyValidator.validate_*(params)
    │
    ├── PASS → StrategyAnalysis(is_valid=True, ...)
    └── FAIL → StrategyAnalysis(is_valid=False, warnings=[...])
    │
    ▼
OptionsStrategyBuilder builds MultiLegOrder
    │
    ▼
OrderRouter.submit_multileg_order(multileg)
    │
    ├── Routes to OptionsExecAdapter (asset_class=OPTION)
    │
    ▼
OptionsExecAdapter.submit_multileg_order(multileg)
    │
    ├── publish("execution.order.submitted")
    └── Track order status → publish fill/cancel/reject events
```

### Event Flow: Expiration Management Flow

```
ExpirationManager.start()
    │
    ▼
Periodic check loop (every check_interval_seconds)
    │
    ▼
ExpirationManager.check_expirations(today)
    │
    ├── For each options position:
    │       │
    │       ├── DTE <= alert_dte (e.g. 7 days)
    │       │       └── publish("options.expiration.warning", {symbol, dte, expiration_date})
    │       │
    │       ├── DTE <= auto_close_dte (e.g. 1 day)
    │       │       ├── Close position via ExecAdapter
    │       │       └── publish("options.position.auto_closed", {symbol, quantity})
    │       │
    │       └── roll_enabled and DTE <= auto_close_dte
    │               ├── Build roll via OptionsStrategyBuilder
    │               └── publish("options.position.rolled", {symbol, new_expiration})
```

**Channels:** `options.expiration.warning`, `options.position.auto_closed`, `options.position.rolled`

## Component Lifecycle

### Startup Sequence

```
1. Load configuration (config.toml + .env)
2. Initialize structured logging (structlog)
3. Create EventBus
4. Create DataManager with DataConfig
5. Register file providers (CsvBarProvider) if configured
6. Start DataManager → connect and stream all registered providers
7. Create OrderRouter
8. Create PublicComExecAdapter → connect() → authenticate API
   Register with OrderRouter for AssetClass.EQUITY
9. Create CryptoExecAdapter (if crypto credentials configured) → connect()
   Register with OrderRouter for AssetClass.CRYPTO
10. Create OptionsExecAdapter → connect()
    Register with OrderRouter for AssetClass.OPTION
11. Create GreeksProvider (with client and refresh interval)
12. Start portfolio refresh loop
13. Create RiskManager with RiskConfig
14. Create ExpirationManager (with config, event_bus, exec_adapter, strategy_builder) → start()
15. Create BracketOrderManager → wire_events() → subscribe to execution + quote channels
16. Create TrailingStopManager (with event_bus, exec_adapter) → wire_events()
17. Create ScaledOrderManager (with event_bus, exec_adapter) → wire_events()
18. Create StrategyManager (with bracket_manager) → wire_events() → subscribe to market data channels
19. Create Dashboard (FastAPI + DashboardWSManager) → mount ingestion routes → start()
20. Start uvicorn server
21. Publish system ready event
```

### Shutdown Sequence

```
1. Receive SIGINT or SIGTERM
2. StrategyManager.stop_all() → stop all active strategies
3. StrategyManager.unwire_events() → unsubscribe from channels
4. ScaledOrderManager.unwire_events() → unsubscribe from execution channels
5. TrailingStopManager.unwire_events() → unsubscribe from quote + execution channels
6. BracketOrderManager.unwire_events() → unsubscribe from execution + quote channels
7. ExpirationManager.stop() → cancel expiration monitoring loop
8. DashboardWSManager.stop() → close WebSocket connections
9. OrderRouter.disconnect() → disconnect all registered adapters
10. DataManager.stop() → disconnect all providers, cancel streaming tasks
11. Uvicorn server shutdown
```

## Async Patterns

The platform is built entirely on `asyncio`:

- **Data streaming** — Long-lived tasks consuming from DataProvider async iterators
- **Event bus** — `asyncio.gather` dispatches to all subscribers concurrently
- **Order tracking** — `asyncio.create_task` spawns a background poller for each order
- **Portfolio refresh** — Periodic `asyncio.sleep` loop fetching portfolio state
- **Dashboard** — FastAPI with uvicorn ASGI server, WebSocket broadcast via asyncio tasks
- **Signal handling** — `asyncio.Event` for graceful shutdown on SIGINT/SIGTERM

## Module Dependency Diagram

```
trading_platform.main
    ├── core.config (load_settings)
    ├── core.logging (setup_logging, get_logger)
    ├── core.events (EventBus)
    ├── core.enums (Channel)
    ├── core.order_router (OrderRouter)
    │
    ├── data.manager (DataManager)
    │   ├── data.provider (DataProvider ABC)
    │   ├── data.file_provider (CsvBarProvider)
    │   ├── data.config (DataConfig)
    │   └── data.ingestion_server (mount_ingestion_routes)
    │
    ├── adapters.public_com.adapter (PublicComExecAdapter)
    │   ├── adapters.public_com.client (PublicComClient)
    │   └── adapters.public_com.parse (sdk_*_to_platform)
    │
    ├── adapters.crypto.adapter (CryptoExecAdapter)
    │
    ├── adapters.options.adapter (OptionsExecAdapter)
    │
    ├── bracket.manager (BracketOrderManager)
    │   ├── bracket.models (BracketOrder)
    │   └── bracket.enums (BracketState, BracketChannel)
    │
    ├── orders.trailing_stop (TrailingStopManager)
    │   └── models (TrailingStop, TrailingStopState)
    │
    ├── orders.scaled (ScaledOrderManager)
    │   └── models (ScaledExitOrder, ScaledEntryOrder, Tranche, ScaledOrderState)
    │
    ├── options.strategy_builder (OptionsStrategyBuilder)
    │   └── options.strategies (VerticalSpreadParams, IronCondorParams, ...)
    │
    ├── options.validator (StrategyValidator)
    │   └── options.strategies (StrategyAnalysis)
    │
    ├── options.greeks (GreeksProvider)
    │   └── models (GreeksData, AggregatedGreeks)
    │
    ├── options.expiration (ExpirationManager)
    │   └── models (ExpirationConfig, OptionsPosition)
    │
    ├── strategy.manager (StrategyManager)
    │   ├── strategy.base (Strategy ABC)
    │   └── strategy.context (StrategyContext → BracketOrderManager)
    │
    ├── risk.manager (RiskManager)
    │   ├── risk.checks (check_*)
    │   ├── risk.greeks_checks (check_portfolio_delta, check_portfolio_gamma, ...)
    │   └── risk.models (RiskConfig, RiskState, RiskViolation)
    │
    └── dashboard.app (create_app)
        └── dashboard.ws (DashboardWSManager)
```

## Data Flow

### Market Data Pipeline

Data enters the platform through three paths, all converging on the EventBus:

1. **File providers** — `CsvBarProvider` loads historical data and yields `Bar` objects via async iterators
2. **REST ingestion** — External systems POST to `/api/data/bars`, `/api/data/quotes`, `/api/data/trades`
3. **WebSocket ingestion** — External systems stream data via `ws://host:port/ws/data`

All paths flow through `DataManager`, which publishes to `Channel.QUOTE`, `Channel.TRADE`, and `Channel.BAR`:

4. **StrategyManager** dispatches to all active strategies via `dispatch_quote()`, `dispatch_trade()`, `dispatch_bar()`
5. **DashboardWSManager** broadcasts to connected WebSocket clients

### Execution Pipeline

1. **Strategy** generates a signal in `on_bar()` / `on_quote()` / `on_trade()`
2. **Strategy** calls `self.context.submit_order(order)`
3. **StrategyContext** runs `RiskManager.pre_trade_check()` — rejects if any check fails
4. **StrategyContext** calls `PublicComExecAdapter.submit_order()`
5. **Adapter** builds SDK `OrderRequest`, calls Public.com API
6. **Adapter** publishes `execution.order.submitted` and starts tracking
7. **Order tracker** polls for status updates, publishes fill/cancel/reject events

### Portfolio Pipeline

1. **PublicComExecAdapter** runs a background loop every `portfolio_refresh` seconds
2. **Loop** calls `sync_portfolio()` → fetches positions and buying power from Public.com
3. **Adapter** publishes `execution.portfolio.update` and `execution.account.update`
4. **StrategyManager** dispatches position updates to active strategies
5. **RiskManager** updates portfolio value for concentration and drawdown checks
