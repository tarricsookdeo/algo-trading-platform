# Algo Trading Platform

A production-oriented live algorithmic trading platform built in Python. Event-driven architecture with bring-your-own-data (BYOD) ingestion, live order execution (Public.com), automated strategy management, risk controls, and a real-time monitoring dashboard.

## Features

- **Bring-your-own-data** — Ingest market data from any source via file loading (CSV), REST POST, WebSocket streaming, or custom Python providers
- **Live order execution** — Equity orders, single-leg options, and multi-leg spreads via Public.com
- **Crypto trading** — 24/7 crypto execution adapter with fractional Decimal quantities, portfolio sync, and order tracking
- **Options trading** — Full options chain with multi-leg strategy builder (verticals, iron condors, straddles, strangles, butterflies, calendars), greeks provider with caching, and expiration management with auto-close and rolling
- **Synthetic bracket orders** — Framework-managed entry + stop-loss + take-profit lifecycle with bid-price monitoring
- **Trailing stops** — Ratcheting stop-loss orders that follow price upward via cancel-and-replace, with configurable trail amount or percentage
- **Scaled orders** — Multi-tranche entries and exits with proportional quantity allocation and automatic stop-loss adjustment as tranches fill
- **Strategy framework** — Abstract base class with lifecycle management, event-driven signal generation, and order submission
- **Risk management** — 6 pre-trade checks, 2 post-trade checks, greeks-aware risk checks (delta, gamma, theta, vega limits), automatic trading halts, and configurable limits
- **Monitoring dashboard** — FastAPI-powered UI with real-time WebSocket updates, REST API, and system metrics for all order types including trailing stops, scaled orders, brackets, and options greeks
- **Performance pipeline** — Internal message queue with batch processing, quote deduplication, lossy/lossless modes, dashboard throttling, real-time performance metrics, and optional uvloop for 2–4x faster async I/O
- **Event-driven architecture** — Async pub/sub event bus connecting all components with wildcard subscriptions

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Dashboard (FastAPI)                              │
│  REST API ← EventBus → WebSocket (live updates)                       │
│  Endpoints: status, portfolio, orders, strategies, risk, P&L,         │
│    trailing-stops, scaled-orders, brackets, options/greeks/expirations │
├───────────────────────────────────────────────────────────────────────┤
│                       Strategy Manager                                 │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  Strategy (ABC)  ←  StrategyContext  →  RiskManager              │  │
│  │  on_quote / on_trade / on_bar → signals → submit_order           │  │
│  │  submit_bracket_order │ trailing_stop │ scaled_order              │  │
│  └─────────────────────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────────────────────┤
│  Order Managers          │  Risk Manager                               │
│  ┌─────────────────────┐ │  Pre-trade: 6 checks + greeks limits       │
│  │ BracketOrderManager │ │  Post-trade: drawdown, daily trade count   │
│  │ TrailingStopManager │ │  Greeks: delta, gamma, theta, vega limits  │
│  │ ScaledOrderManager  │ │  Halt: automatic trading halt on breach    │
│  └─────────────────────┘ │                                             │
├───────────────────────────────────────────────────────────────────────┤
│                          Event Bus                                     │
│  Market: quote │ trade │ bar │ status    Exec: execution.order.*      │
│  Bracket: bracket.*   Trailing: trailing_stop.*   Scaled: scaled.*    │
│  Options: options.*   Risk: risk.*   Strategy: strategy.signal        │
├───────────────────────────────────────────────────────────────────────┤
│                    Data & Execution Layer                               │
│  ┌───────────────────┐  ┌────────────────────────────────────────┐   │
│  │ DataManager (BYOD) │  │  OrderRouter (ExecAdapter)              │   │
│  │ ┌───────────────┐ │  │  ┌────────────┐ ┌──────────────────┐  │   │
│  │ │ CSV Providers  │ │  │  │ Public.com │ │ Crypto Adapter   │  │   │
│  │ │ REST Ingestion │ │  │  │ Equities   │ │ 24/7 fractional  │  │   │
│  │ │ WS Ingestion   │ │  │  │ + Options  │ │ Decimal qty      │  │   │
│  │ │ Custom         │ │  │  ├────────────┤ ├──────────────────┤  │   │
│  │ └───────────────┘ │  │  │ Options    │ │ Portfolio sync   │  │   │
│  └───────────────────┘  │  │ Adapter    │ └──────────────────┘  │   │
│                          │  └────────────┘                        │   │
│  ┌───────────────────┐  │  ┌────────────────────────────────────┐│   │
│  │ Options Components │  │  │ OptionsStrategyBuilder │ Validator ││   │
│  │ GreeksProvider     │  │  │ ExpirationManager                 ││   │
│  └───────────────────┘  │  └────────────────────────────────────┘│   │
│                          └────────────────────────────────────────┘   │
├───────────────────────────────────────────────────────────────────────┤
│                         Core Domain                                    │
│  Models: QuoteTick, TradeTick, Bar, Order, Position, MultiLegOrder   │
│  Config │ Logging (structlog) │ Clock │ Enums │ OrderRouter           │
└───────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
```


```bash
```

### 2. Configure

Copy the environment template and add your API credentials:

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required environment variables (for execution only — platform runs without these):

| Variable | Description |
|----------|-------------|
| `PUBLIC_API_SECRET` | Public.com API secret (execution) |
| `PUBLIC_ACCOUNT_ID` | Public.com account ID |

Edit `config.toml` to customize data ingestion, risk limits, dashboard port, and platform settings.

### 3. Run

```bash
trading-platform
# or
python -m trading_platform.main
```

Options:
- `--config path/to/config.toml` — custom config file
- `--log-level DEBUG` — override log level

### 4. Ingest Data

**From CSV files** — set `csv_directory` in `config.toml`:

```toml
[data]
csv_directory = "/path/to/your/csvs"
```

**Via REST API** — POST data to the running platform:

```bash
curl -X POST http://localhost:8080/api/data/bars \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","open":185.0,"high":186.0,"low":184.5,"close":185.5,"volume":10000,"timestamp":"2024-01-15T09:30:00"}'
```

**Via WebSocket** — stream data in real time:

```python
import websockets, json, asyncio

async def stream():
    async with websockets.connect("ws://localhost:8080/ws/data") as ws:
        await ws.send(json.dumps({
            "type": "bar",
            "data": {"symbol": "AAPL", "open": 185.0, "high": 186.0, "low": 184.5, "close": 185.5, "volume": 10000, "timestamp": "2024-01-15T09:30:00"}
        }))
        print(await ws.recv())

asyncio.run(stream())
```

**Custom provider** — implement the `DataProvider` ABC:

```python
from trading_platform.data.provider import DataProvider

class MyProvider(DataProvider):
    @property
    def name(self) -> str: return "my-source"
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def is_connected(self) -> bool: ...
    async def stream_bars(self, symbols): ...
```

### 5. Dashboard

Open `http://localhost:8080` in your browser. The dashboard shows:
- Data provider status and ingestion stats
- Portfolio positions and P&L
- Active strategies and signals
- Risk state and violations
- Order management (submit, cancel)
- System metrics (msg/sec, memory, uptime)

## Project Structure

```
src/trading_platform/
├── main.py                  # Entry point and startup orchestration
├── core/
│   ├── events.py            # Async event bus (pub/sub with wildcards)
│   ├── models.py            # Domain models (Pydantic)
│   ├── config.py            # Config management (.env + TOML)
│   ├── logging.py           # Structured logging (structlog)
│   ├── clock.py             # System clock
│   ├── enums.py             # Enumerations (Channel, OrderSide, etc.)
│   ├── order_router.py      # OrderRouter — dispatches by AssetClass
│   ├── message_queue.py     # Async bounded message queue (lossy/lossless)
│   └── metrics.py           # PerformanceMetrics (throughput, latency, drops)
├── data/
│   ├── provider.py          # DataProvider abstract base class
│   ├── manager.py           # DataManager (provider orchestration)
│   ├── file_provider.py     # CsvBarProvider for historical CSV data
│   ├── config.py            # DataConfig settings
│   └── ingestion_server.py  # REST + WebSocket ingestion endpoints
├── adapters/
│   ├── base.py              # ExecAdapter ABC
│   ├── public_com/
│   │   ├── adapter.py       # Public.com execution adapter
│   │   ├── client.py        # Public.com API client
│   │   ├── parse.py         # Response parsers
│   │   └── config.py        # Public.com configuration
│   ├── crypto/
│   │   ├── adapter.py       # CryptoExecAdapter (24/7, fractional qty)
│   │   ├── client.py        # CryptoClient API wrapper
│   │   └── config.py        # CryptoConfig settings
│   └── options/
│       ├── adapter.py       # OptionsExecAdapter (single & multi-leg)
│       ├── client.py        # OptionsClient API wrapper
│       └── config.py        # OptionsConfig settings
├── options/
│   ├── greeks.py            # GreeksProvider, GreeksData, AggregatedGreeks
│   ├── strategies.py        # Strategy parameter dataclasses
│   ├── strategy_builder.py  # OptionsStrategyBuilder (multi-leg builder)
│   ├── validator.py         # StrategyValidator (validation + risk/reward)
│   └── expiration.py        # ExpirationManager, ExpirationConfig
├── orders/
│   ├── trailing_stop.py     # TrailingStopManager, TrailingStop
│   └── scaled.py            # ScaledOrderManager, ScaledExitOrder, ScaledEntryOrder
├── bracket/
│   ├── manager.py           # BracketOrderManager
│   ├── models.py            # BracketOrder model
│   └── enums.py             # BracketState, BracketChannel
├── strategy/
│   ├── base.py              # Strategy abstract base class
│   ├── context.py           # StrategyContext (market data + order API)
│   ├── manager.py           # StrategyManager (lifecycle, event wiring)
│   └── examples/
│       └── sma_crossover.py # SMA crossover example strategy
├── risk/
│   ├── checks.py            # Pre-trade and post-trade check functions
│   ├── greeks_checks.py     # Greeks-aware risk checks (delta, gamma, theta, vega)
│   ├── manager.py           # RiskManager (orchestrates checks, halts)
│   └── models.py            # RiskConfig, RiskState, RiskViolation
└── dashboard/
    ├── app.py               # FastAPI application and REST endpoints
    ├── ws.py                # WebSocket manager (DashboardWSManager)
    ├── throttler.py         # DashboardThrottler (buffer → dedup → batch flush)
    └── static/index.html    # Dashboard UI
docs/
├── README.md                # Documentation index
├── architecture.md          # Architecture guide
├── getting-started.md       # Getting started guide
├── configuration.md         # Configuration reference
├── adapters.md              # Data providers & execution adapter guide
├── strategies.md            # Strategy development guide
├── risk-management.md       # Risk management guide
├── dashboard.md             # Dashboard guide
├── event-bus.md             # Event bus reference
└── api-reference.md         # API reference
```

## Configuration Reference

### .env (secrets)

| Variable | Description |
|----------|-------------|
| `PUBLIC_API_SECRET` | Public.com API secret |
| `PUBLIC_ACCOUNT_ID` | Public.com account ID |
| `CRYPTO_API_SECRET` | Crypto exchange API secret |
| `CRYPTO_ACCOUNT_ID` | Crypto exchange account ID |
| `OPTIONS_API_SECRET` | Options API secret (if separate from Public.com) |
| `OPTIONS_ACCOUNT_ID` | Options account ID |

### config.toml

```toml
[data]
ingestion_enabled = true           # Enable data ingestion endpoints
csv_directory = ""                 # Path to CSV files/directory (optional)
replay_speed = 0.0                 # Replay speed multiplier (0 = instant)
max_bars_per_request = 10000       # Max bars per REST ingestion request

[public_com]
poll_interval = 2.0                # Order status poll interval (seconds)
portfolio_refresh = 30.0           # Portfolio sync interval (seconds)

[crypto]
trading_pairs = ["BTC-USD", "ETH-USD"]
poll_interval = 2.0                # Order status poll interval (seconds)
portfolio_refresh = 30.0           # Portfolio sync interval (seconds)

[options]
poll_interval = 2.0
portfolio_refresh = 30.0

[trailing_stop]
# Defaults are built into TrailingStopManager; override here if needed

[expiration]
auto_close_dte = 1                 # Auto-close positions at this DTE
alert_dte = 7                      # Alert when DTE reaches this threshold
roll_enabled = false               # Enable automatic rolling
roll_target_dte = 30               # Target DTE when rolling

[risk]
max_position_size = 1000.0         # Max shares per symbol
max_position_concentration = 0.10  # Max 10% in one name
max_order_value = 50000.0          # Max $ per order
daily_loss_limit = -5000.0         # Halt trading if daily P&L below this
max_open_orders = 20
max_daily_trades = 100
max_portfolio_drawdown = 0.15      # Halt on 15% drawdown

[risk.greeks]
max_portfolio_delta = 500.0        # Max absolute portfolio delta
max_portfolio_gamma = 100.0        # Max absolute portfolio gamma
max_daily_theta = -200.0           # Max daily theta decay
max_portfolio_vega = 1000.0        # Max absolute portfolio vega

[performance]
message_queue_size = 50000         # Internal queue capacity
message_queue_mode = "lossy"       # "lossy" (drop oldest) or "lossless" (backpressure)
consumer_batch_size = 100          # Messages per consumer batch
consumer_flush_interval_ms = 10    # Max wait before flushing batch (ms)
dedup_quotes_in_batch = true       # Deduplicate quotes per symbol in each batch

[dashboard]
host = "0.0.0.0"
port = 8080
update_interval_ms = 100           # Dashboard throttler flush interval (ms)
max_trades_per_flush = 50          # Max trade events per throttled flush

[platform]
log_level = "INFO"
symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
```

See [docs/configuration.md](docs/configuration.md) for the complete configuration reference.

## Documentation

Full documentation is available in the [`docs/`](docs/) directory:

- [Documentation Index](docs/README.md)
- [Architecture Guide](docs/architecture.md) — system design, event flow, component lifecycle
- [Getting Started](docs/getting-started.md) — installation, configuration, first run
- [Configuration Reference](docs/configuration.md) — all config options with examples
- [Data Providers & Adapters](docs/adapters.md) — BYOD data providers, Public.com, crypto, and options execution
- [Strategy Development](docs/strategies.md) — writing and running trading strategies
- [Risk Management](docs/risk-management.md) — risk checks, greeks limits, halts, configuration
- [Performance Guide](docs/performance.md) — message queue, throttling, metrics, tuning
- [Dashboard Guide](docs/dashboard.md) — UI features, REST API, WebSocket API
- [Event Bus Reference](docs/event-bus.md) — channels, payloads, subscription patterns
- [API Reference](docs/api-reference.md) — all public classes and methods

## Testing

```bash
pytest tests/ -v
```

## Phase Roadmap

- [x] **Phase 1**: Core infrastructure (event bus, models, config, logging)
- [x] **Phase 2**: BYOD data ingestion (DataProvider ABC, DataManager, file providers, REST/WS ingestion)
- [x] **Phase 3**: Public.com execution adapter (orders, portfolio, preflight)
- [x] **Phase 4**: Strategy framework (base class, context, manager, SMA crossover example)
- [x] **Phase 5**: Risk controls (pre-trade checks, post-trade checks, trading halts)
- [x] **Phase 6**: Dashboard enhancements (portfolio, orders, strategies, risk, P&L, data ingestion)
- [x] **Phase 7**: Documentation and examples
- [x] **Phase A**: Crypto execution adapter (24/7 trading, fractional Decimal quantities, portfolio sync)
- [x] **Phase B**: Options order model, adapter, and routing (OrderRouter, single-leg + multi-leg)
- [x] **Phase C**: Options strategy builder (verticals, iron condors, straddles, strangles, butterflies, calendars)
- [x] **Phase D**: Trailing stops, scaled orders, and bracket integration
- [x] **Phase E**: Greeks-aware risk checks and expiration management
- [x] **Phase F**: Dashboard updates, documentation, and examples
- [x] **Performance Phase 1**: Internal message queue, dashboard throttling, batch endpoints, performance metrics
