# Architecture Guide

## System Overview

The algo trading platform is a production-oriented, event-driven system built in Python. All components communicate through a central async event bus — there is no direct coupling between data ingestion, strategy logic, risk management, execution, or the monitoring dashboard.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Dashboard (FastAPI + WebSocket)                     │
│   REST API: /api/status, /api/portfolio, /api/orders, /api/strategies    │
│   WebSocket: /ws (quotes, trades, bars, metrics, portfolio, risk)        │
│   Data Ingestion: POST /api/data/bars, /quotes, /trades; WS /ws/data    │
├─────────────────────────────────────────────────────────────────────────┤
│                              Event Bus                                   │
│  Market: quote │ trade │ bar │ status     Strategy: signal │ lifecycle   │
│  Exec: order.submitted │ .filled │ ...   Risk: check.* │ alert │ halt  │
│  Bracket: bracket.entry.filled │ .stopped_out │ .take_profit.* │ ...   │
│  System: system │ error                  Portfolio: portfolio │ account  │
├───────────────┬──────────────────┬───────────────────┬──────────────────┤
│  DataManager  │   Public.com     │  Bracket Manager   │  Strategy Mgr   │  Risk Manager   │
│  (BYOD)       │   Exec Adapter   │                    │                 │                 │
│               │                  │  Entry → SL → TP   │  ┌───────────┐ │  Pre-trade:     │
│ ┌───────────┐ │  Order placement │  SL rests live     │  │ Strategy  │ │  6 checks       │
│ │ CSV/Parq  │ │  Cancel/replace  │  TP via bid watch  │  │ ┌───────┐│ │                 │
│ │ Providers │ │  Portfolio sync  │                    │  │ │Context││ │  Post-trade:    │
│ ├───────────┤ │  Account info   │  State machine:    │  │ └───────┘│ │  2 checks       │
│ │ REST      │ │                  │  PENDING_ENTRY →   │  │ on_bar() │ │                 │
│ │ Ingestion │ │  Auth:           │  ENTRY_PLACED →    │  │ on_quote│ │  Halt/resume    │
│ ├───────────┤ │  ApiKeyAuthConfig│  MONITORING →      │  └───────────┘ │                 │
│ │ WebSocket │ │  Auto-refresh   │  STOPPED_OUT or    │                 │                 │
│ │ Ingestion │ │                  │  TP_FILLED         │                 │                 │
│ ├───────────┤ │                  │                    │                 │                 │
│ │ Custom    │ │                  │                    │                 │                 │
│ │ Providers │ │                  │                    │                 │                 │
│ └───────────┘ │                  │                    │                 │                 │
├───────────────┴──────────────────┴───────────────────┴─────────────────┴─────────────────┤
│                           Core Domain                                    │
│  Models: QuoteTick, TradeTick, Bar, Order, Position, Fill, Instrument   │
│  Config (Pydantic Settings) │ Logging (structlog) │ Clock │ Enums       │
└─────────────────────────────────────────────────────────────────────────┘
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

## Component Lifecycle

### Startup Sequence

```
1. Load configuration (config.toml + .env)
2. Initialize structured logging (structlog)
3. Create EventBus
4. Create DataManager with DataConfig
5. Register file providers (CsvBarProvider) if configured
6. Start DataManager → connect and stream all registered providers
7. Create PublicComExecAdapter → connect() → authenticate API
8. Start portfolio refresh loop
9. Create RiskManager with RiskConfig
10. Create BracketOrderManager → wire_events() → subscribe to execution + quote channels
11. Create StrategyManager (with bracket_manager) → wire_events() → subscribe to market data channels
12. Create Dashboard (FastAPI + DashboardWSManager) → mount ingestion routes → start()
13. Start uvicorn server
14. Publish system ready event
```

### Shutdown Sequence

```
1. Receive SIGINT or SIGTERM
2. StrategyManager.stop_all() → stop all active strategies
3. StrategyManager.unwire_events() → unsubscribe from channels
4. BracketOrderManager.unwire_events() → unsubscribe from execution + quote channels
5. DashboardWSManager.stop() → close WebSocket connections
6. PublicComExecAdapter.disconnect() → cancel portfolio refresh, close client
7. DataManager.stop() → disconnect all providers, cancel streaming tasks
8. Uvicorn server shutdown
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
