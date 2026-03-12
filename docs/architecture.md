# Architecture Guide

## System Overview

The algo trading platform is a production-oriented, event-driven system built in Python. All components communicate through a central async event bus — there is no direct coupling between data ingestion, strategy logic, risk management, execution, or the monitoring dashboard.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Dashboard (FastAPI + WebSocket)                     │
│   REST API: /api/status, /api/portfolio, /api/orders, /api/strategies    │
│   WebSocket: /ws (quotes, trades, bars, metrics, portfolio, risk)        │
├─────────────────────────────────────────────────────────────────────────┤
│                              Event Bus                                   │
│  Market: quote │ trade │ bar │ status     Strategy: signal │ lifecycle   │
│  Exec: order.submitted │ .filled │ ...   Risk: check.* │ alert │ halt  │
│  System: system │ error                  Portfolio: portfolio │ account  │
├───────────────┬──────────────────┬───────────────────┬──────────────────┤
│  Alpaca Data  │   Public.com     │  Strategy Manager  │  Risk Manager   │
│   Adapter     │   Exec Adapter   │                    │                 │
│               │                  │  ┌──────────────┐  │  Pre-trade:     │
│ ┌───────────┐ │  Order placement │  │  Strategy     │  │  6 checks      │
│ │ SIP Stock │ │  Cancel/replace  │  │  ┌──────────┐│  │                 │
│ │ Stream    │ │  Portfolio sync  │  │  │ Context  ││  │  Post-trade:    │
│ │ (WS/JSON) │ │  Account info   │  │  └──────────┘│  │  2 checks       │
│ ├───────────┤ │                  │  │  on_quote()  │  │                 │
│ │ OPRA Opts │ │  Auth:           │  │  on_trade()  │  │  Halt/resume    │
│ │ Stream    │ │  ApiKeyAuthConfig│  │  on_bar()    │  │                 │
│ │ (WS/msgpk)│ │  Auto-refresh   │  │  on_signal() │  │                 │
│ ├───────────┤ │                  │  └──────────────┘  │                 │
│ │ REST      │ │                  │                    │                 │
│ │ Client    │ │                  │                    │                 │
│ │ (httpx)   │ │                  │                    │                 │
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

### Event Flow: Market Data → Dashboard

```
Alpaca WebSocket → parse message → publish(Channel.QUOTE, QuoteTick)
                                        │
                    ┌───────────────────┤
                    ▼                    ▼
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
4. Create AlpacaDataAdapter → connect() → authenticate WebSocket
5. Subscribe to configured symbols (trades, quotes, bars)
6. Create PublicComExecAdapter → connect() → authenticate API
7. Start portfolio refresh loop
8. Create RiskManager with RiskConfig
9. Create StrategyManager → wire_events() → subscribe to market data channels
10. Create Dashboard (FastAPI + DashboardWSManager) → start()
11. Start uvicorn server
12. Publish system ready event
```

### Shutdown Sequence

```
1. Receive SIGINT or SIGTERM
2. StrategyManager.stop_all() → stop all active strategies
3. StrategyManager.unwire_events() → unsubscribe from channels
4. DashboardWSManager.stop() → close WebSocket connections
5. PublicComExecAdapter.disconnect() → cancel portfolio refresh, close client
6. AlpacaDataAdapter.disconnect() → close WebSocket streams, close REST client
7. Uvicorn server shutdown
```

## Async Patterns

The platform is built entirely on `asyncio`:

- **WebSocket streams** — Long-lived tasks reading from Alpaca's SIP and OPRA feeds
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
    ├── adapters.alpaca.adapter (AlpacaDataAdapter)
    │   ├── adapters.alpaca.stream (AlpacaStockStream, AlpacaOptionsStream)
    │   ├── adapters.alpaca.client (AlpacaClient)
    │   ├── adapters.alpaca.provider (AlpacaInstrumentProvider)
    │   └── adapters.alpaca.parse (parse_stock_*, parse_option_*)
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

1. **Alpaca WebSocket** receives raw JSON (stocks) or msgpack (options) messages
2. **Parsers** (`adapters/alpaca/parse.py`) convert to domain models (`QuoteTick`, `TradeTick`, `Bar`)
3. **Adapter** publishes to EventBus on `Channel.QUOTE`, `Channel.TRADE`, `Channel.BAR`
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
