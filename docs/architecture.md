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
│  System: system │ error                  Portfolio: portfolio │ account  │
├───────────────┬──────────────────┬───────────────────┬──────────────────┤
│  DataManager  │   Public.com     │  Strategy Manager  │  Risk Manager   │
│  (BYOD)       │   Exec Adapter   │                    │                 │
│               │                  │  ┌──────────────┐  │  Pre-trade:     │
│ ┌───────────┐ │  Order placement │  │  Strategy     │  │  6 checks      │
│ │ CSV/Parq  │ │  Cancel/replace  │  │  ┌──────────┐│  │                 │
│ │ Providers │ │  Portfolio sync  │  │  │ Context  ││  │  Post-trade:    │
│ ├───────────┤ │  Account info   │  │  └──────────┘│  │  2 checks       │
│ │ REST      │ │                  │  │  on_quote()  │  │                 │
│ │ Ingestion │ │  Auth:           │  │  on_trade()  │  │  Halt/resume    │
│ ├───────────┤ │  ApiKeyAuthConfig│  │  on_bar()    │  │                 │
│ │ WebSocket │ │  Auto-refresh   │  │  on_signal() │  │                 │
│ │ Ingestion │ │                  │  └──────────────┘  │                 │
│ ├───────────┤ │                  │                    │                 │
│ │ Custom    │ │                  │                    │                 │
│ │ Providers │ │                  │                    │                 │
│ └───────────┘ │                  │                    │                 │
├───────────────┴──────────────────┴───────────────────┴──────────────────┤
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

## Component Lifecycle

### Startup Sequence

```
1. Load configuration (config.toml + .env)
2. Initialize structured logging (structlog)
3. Create EventBus
4. Create DataManager with DataConfig
5. Register file providers (CsvBarProvider / ParquetBarProvider) if configured
6. Start DataManager → connect and stream all registered providers
7. Create PublicComExecAdapter → connect() → authenticate API
8. Start portfolio refresh loop
9. Create RiskManager with RiskConfig
10. Create StrategyManager → wire_events() → subscribe to market data channels
11. Create Dashboard (FastAPI + DashboardWSManager) → mount ingestion routes → start()
12. Start uvicorn server
13. Publish system ready event
```

### Shutdown Sequence

```
1. Receive SIGINT or SIGTERM
2. StrategyManager.stop_all() → stop all active strategies
3. StrategyManager.unwire_events() → unsubscribe from channels
4. DashboardWSManager.stop() → close WebSocket connections
5. PublicComExecAdapter.disconnect() → cancel portfolio refresh, close client
6. DataManager.stop() → disconnect all providers, cancel streaming tasks
7. Uvicorn server shutdown
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
    │   ├── data.file_provider (CsvBarProvider, ParquetBarProvider)
    │   ├── data.config (DataConfig)
    │   └── data.ingestion_server (mount_ingestion_routes)
    │
    ├── adapters.public_com.adapter (PublicComExecAdapter)
    │   ├── adapters.public_com.client (PublicComClient)
    │   └── adapters.public_com.parse (sdk_*_to_platform)
    │
    ├── strategy.manager (StrategyManager)
    │   ├── strategy.base (Strategy ABC)
    │   └── strategy.context (StrategyContext)
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

1. **File providers** — `CsvBarProvider` / `ParquetBarProvider` load historical data and yield `Bar` objects via async iterators
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
