# Architecture Guide

## System Overview

The algo trading platform is a production-oriented, event-driven system built in Python. All components communicate through a central async event bus — there is no direct coupling between data ingestion, strategy logic, risk management, execution, or the monitoring dashboard.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Dashboard (FastAPI + WebSocket)                         │
│  REST: /api/status, /portfolio, /orders, /strategies, /risk, /pnl             │
│        /trailing-stops, /scaled-orders, /brackets, /options/greeks/*          │
│  WebSocket: /ws (quotes, trades, bars, metrics, portfolio, risk)              │
│  Ingestion: POST /api/data/bars, /quotes, /trades; WS /ws/data               │
├──────────────────────────────────────────────────────────────────────────────┤
│                               Event Bus                                       │
│  Market: quote │ trade │ bar │ status       Strategy: signal │ lifecycle      │
│  Exec: execution.order.* │ .portfolio.*    Risk: check.* │ alert │ halt      │
│  Bracket: bracket.*   Trailing: trailing_stop.*   Scaled: scaled.*           │
│  Options: options.*   System: system │ error   Portfolio: portfolio │ account │
├─────────────┬───────────────────┬──────────────────┬─────────────────────────┤
│ DataManager │  OrderRouter      │  Order Managers   │  Strategy & Risk        │
│ (BYOD)      │  (ExecAdapter)    │                   │                         │
│             │                   │  BracketManager   │  StrategyManager        │
│ CSV/Parquet │  ┌─────────────┐  │  TrailingStopMgr  │  ┌───────────────────┐ │
│ REST Ingest │  │ Public.com  │  │  ScaledOrderMgr   │  │ Strategy (ABC)    │ │
│ WS Ingest   │  │ (Equity +   │  │                   │  │ ← StrategyContext │ │
│ Custom      │  │  Options)   │  │                   │  └───────────────────┘ │
│             │  ├─────────────┤  │                   │                         │
│             │  │ Crypto      │  │                   │  RiskManager            │
│             │  │ (24/7)      │  │                   │  Pre: 6 checks          │
│             │  ├─────────────┤  │                   │  Greeks: delta/gamma/   │
│             │  │ Options     │  │                   │    theta/vega limits    │
│             │  │ (multi-leg) │  │                   │  Post: drawdown, count  │
│             │  └─────────────┘  │                   │                         │
├─────────────┴───────────────────┴──────────────┬────┴─────────────────────────┤
│  Options Components                             │  Core Domain                 │
│  GreeksProvider (cache + aggregation)           │  Models: Order, Position,    │
│  OptionsStrategyBuilder + StrategyValidator     │    QuoteTick, Bar, Fill,     │
│  ExpirationManager (auto-close, alerts, roll)   │    MultiLegOrder, Instrument │
│                                                 │  Config │ Logging │ Clock    │
│                                                 │  Enums │ OrderRouter         │
└─────────────────────────────────────────────────┴────────────────────────────┘
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
REST POST /api/data/bars     ├→ DataManager ──→ MessageQueue (async bounded)
WebSocket /ws/data           ─┘                       │
REST POST /api/data/*/batch ─┘                  Consumer (batch + dedup)
                                                      │
                                               publish(Channel.BAR, Bar)
                                                      │
                                   ┌──────────────────┤
                                   ▼                   ▼
                           DashboardWSManager       StrategyManager
                           (throttled broadcast)    (dispatch to strategies)
                                   │
                           DashboardThrottler
                           (buffer → dedup → flush at interval)
                                   │
                           WebSocket clients
```

The **MessageQueue** decouples ingestion from processing. In lossy mode it drops
the oldest message when full; in lossless mode it applies back-pressure. The
consumer drains the queue in configurable batches, optionally deduplicating
quotes (keeping the latest per symbol within each batch).

The **DashboardThrottler** sits between the EventBus and WebSocket clients. It
buffers high-frequency market data (quotes, trades, bars), deduplicates by
symbol, caps trades per flush, and sends a single batch message at a fixed
interval (default 100 ms), reducing broadcast volume from thousands/sec to ~10/sec.

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

### Event Flow: Crypto Execution

```
StrategyContext.submit_order(order)  [order.asset_class == CRYPTO]
    │
    ▼
OrderRouter.submit_order()
    │
    ├── Dispatch to CryptoExecAdapter
    │
    ▼
CryptoExecAdapter.submit_order(order)
    │
    ├── Build SDK order (Decimal quantities)
    ├── publish("execution.order.submitted")
    │
    ▼
_track_order() (async polling)
    │
    ├── publish("execution.order.filled")
    └── publish("execution.order.cancelled")

CryptoExecAdapter._portfolio_refresh_loop()  [runs every portfolio_refresh seconds]
    │
    ├── sync_portfolio() → fetch positions + buying power
    ├── publish("execution.portfolio.update")
    └── publish("execution.account.update")
```

### Event Flow: Options Strategy Builder

```
OptionsStrategyBuilder.build_vertical_spread(params)
    │
    ├── StrategyValidator.validate_vertical_spread(params)
    │       │
    │       ├── Check quantity > 0
    │       ├── Check strikes differ
    │       └── Compute max profit / max loss / breakevens → StrategyAnalysis
    │
    ├── Build MultiLegOrder with 2 legs
    │
    ▼
OptionsStrategyBuilder.build_and_submit(params, strategy_type)
    │
    ├── Build + validate → MultiLegOrder
    ├── OptionsExecAdapter.submit_multileg_order()
    └── publish("execution.order.submitted")
```

### Event Flow: Greeks Data

```
GreeksProvider.get_greeks(option_symbol)
    │
    ├── Check cache (TTL-based)
    │   ├── HIT → return cached GreeksData
    │   └── MISS ↓
    │
    ├── Fetch from data source
    ├── Store in cache with timestamp
    └── Return GreeksData(delta, gamma, theta, vega, rho, iv)

GreeksProvider.get_portfolio_greeks(positions)
    │
    ├── For each option position → get_greeks(symbol)
    ├── Multiply each greek by position quantity
    ├── Sum across all positions
    └── Return AggregatedGreeks(total_delta, total_gamma, total_theta, total_vega)
```

### Event Flow: Expiration Management

```
ExpirationManager._check_loop()  [runs every check_interval_seconds]
    │
    ▼
check_expirations()
    │
    ├── For each tracked OptionsPosition:
    │       │
    │       ├── Compute DTE = expiration_date - today
    │       │
    │       ├── DTE <= auto_close_dte?
    │       │   └── YES → close position, publish("options.expiration.auto_closed")
    │       │
    │       ├── DTE <= alert_dte?
    │       │   └── YES → publish("options.expiration.alert")
    │       │
    │       └── roll_enabled AND DTE <= auto_close_dte?
    │           └── YES → roll to roll_target_dte, publish("options.expiration.rolled")
    │
    └── Sleep(check_interval_seconds)
```

### Event Flow: Trailing Stop Ratcheting

```
TrailingStopManager.create_trailing_stop(symbol, qty, trail_amount|trail_percent)
    │
    ├── Place initial stop-loss order
    ├── publish("trailing_stop.created")
    │
    ▼
"quote" events (price monitoring)
    │
    ├── New high price detected?
    │   └── YES → new_stop = highest_price - trail_amount
    │             (or highest_price * (1 - trail_percent))
    │             │
    │             ├── Cancel existing stop order
    │             ├── Place new stop at higher price
    │             ├── Update highest_price, current_stop_price
    │             └── publish("trailing_stop.ratcheted")
    │
    └── Stop order filled?
        └── publish("trailing_stop.completed")
```

### Event Flow: Scaled Order

```
ScaledOrderManager.create_scaled_exit(symbol, tranches, stop_loss_price)
    │
    ├── Create ScaledExitOrder with N tranches
    ├── Place limit sell for each tranche at tranche.price
    ├── publish("scaled.exit.created")
    │
    ▼
"execution.order.filled" events
    │
    ├── Tranche filled?
    │   ├── Mark tranche.filled = True
    │   ├── Reduce remaining_quantity
    │   ├── Adjust stop-loss proportionally
    │   ├── publish("scaled.exit.tranche_filled")
    │   │
    │   └── All tranches filled?
    │       └── publish("scaled.exit.completed")
    │
    └── Stop-loss filled?
        └── Cancel remaining tranche orders
            └── publish("scaled.exit.stopped_out")
```

## Component Lifecycle

### Startup Sequence

```
1.  Load configuration (config.toml + .env)
2.  Initialize structured logging (structlog)
3.  Create EventBus
4.  Create PerformanceMetrics
5.  Create MessageQueue (bounded, lossy/lossless) → start consumer callback
6.  Create DataManager with DataConfig, MessageQueue, PerformanceMetrics
7.  Register file providers (CsvBarProvider) if configured
8.  Start DataManager → connect and stream all registered providers
9.  Create PublicComExecAdapter → connect() → authenticate API
10. Create CryptoExecAdapter → connect() (if crypto credentials set)
11. Create OptionsExecAdapter → connect() (if options credentials set)
12. Create OrderRouter → register adapters by AssetClass (STOCK, CRYPTO, OPTION)
13. Start portfolio refresh loops (equity, crypto, options)
14. Create RiskManager with RiskConfig + GreeksRiskConfig
15. Create GreeksProvider
16. Create ExpirationManager → start() → begin DTE monitoring loop
17. Create OptionsStrategyBuilder (with OptionsExecAdapter + StrategyValidator)
18. Create BracketOrderManager → wire_events()
19. Create TrailingStopManager → wire_events()
20. Create ScaledOrderManager → wire_events()
21. Create StrategyManager → wire_events() → subscribe to market data channels
22. Create DashboardThrottler (flush_interval_ms, max_trades_per_flush)
23. Create Dashboard (FastAPI + DashboardWSManager) → mount ingestion routes → start()
24. Start uvicorn server
25. Publish system ready event
```

### Shutdown Sequence

```
1.  Receive SIGINT or SIGTERM
2.  StrategyManager.stop_all() → stop all active strategies
3.  StrategyManager.unwire_events() → unsubscribe from channels
4.  ScaledOrderManager.unwire_events()
5.  TrailingStopManager.unwire_events()
6.  BracketOrderManager.unwire_events()
7.  ExpirationManager.stop() → cancel DTE monitoring loop
8.  DashboardWSManager.stop() → stop throttler, close WebSocket connections
9.  MessageQueue.stop() → drain remaining messages, cancel consumer task
10. OrderRouter.disconnect() → disconnect all registered adapters
11. DataManager.stop() → disconnect all providers, cancel streaming tasks
12. Uvicorn server shutdown
```

## Async Patterns

The platform is built entirely on `asyncio`:

- **Data streaming** — Long-lived tasks consuming from DataProvider async iterators
- **Message queue** — `asyncio.Queue`-backed bounded queue with an async consumer task draining in configurable batches
- **Event bus** — `asyncio.gather` dispatches to all subscribers concurrently
- **Order tracking** — `asyncio.create_task` spawns a background poller for each order
- **Portfolio refresh** — Periodic `asyncio.sleep` loop fetching portfolio state
- **Dashboard throttling** — Async task buffers market events, flushes at a fixed interval to cap WebSocket broadcast rate
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
    ├── core.message_queue (MessageQueue)
    ├── core.metrics (PerformanceMetrics)
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
    │   ├── adapters.crypto.client (CryptoClient)
    │   └── adapters.crypto.config (CryptoConfig)
    │
    ├── adapters.options.adapter (OptionsExecAdapter)
    │   ├── adapters.options.client (OptionsClient)
    │   └── adapters.options.config (OptionsConfig)
    │
    ├── options.greeks (GreeksProvider, GreeksData, AggregatedGreeks)
    ├── options.strategy_builder (OptionsStrategyBuilder)
    │   ├── options.strategies (VerticalSpreadParams, IronCondorParams, ...)
    │   └── options.validator (StrategyValidator)
    ├── options.expiration (ExpirationManager, ExpirationConfig)
    │
    ├── orders.trailing_stop (TrailingStopManager, TrailingStop)
    ├── orders.scaled (ScaledOrderManager, ScaledExitOrder, ScaledEntryOrder)
    │
    ├── bracket.manager (BracketOrderManager)
    │   ├── bracket.models (BracketOrder)
    │   └── bracket.enums (BracketState, BracketChannel)
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
        ├── dashboard.ws (DashboardWSManager)
        └── dashboard.throttler (DashboardThrottler)
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
3. **StrategyContext** runs `RiskManager.pre_trade_check()` (including greeks checks for options) — rejects if any check fails
4. **StrategyContext** calls `OrderRouter.submit_order()` — routes to the correct adapter by `AssetClass`
5. **Adapter** (PublicCom, Crypto, or Options) builds SDK request and calls the API
6. **Adapter** publishes `execution.order.submitted` and starts tracking
7. **Order tracker** polls for status updates, publishes fill/cancel/reject events

### Portfolio Pipeline

1. Each adapter (PublicCom, Crypto, Options) runs a background loop every `portfolio_refresh` seconds
2. **Loop** calls `sync_portfolio()` → fetches positions and buying power
3. **Adapter** publishes `execution.portfolio.update` and `execution.account.update`
4. **StrategyManager** dispatches position updates to active strategies
5. **RiskManager** updates portfolio value for concentration, drawdown, and greeks checks
