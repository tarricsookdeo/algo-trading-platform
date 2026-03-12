# Algo Trading Platform

A production-oriented live algorithmic trading platform built in Python. Event-driven architecture with bring-your-own-data (BYOD) ingestion, live order execution (Public.com), automated strategy management, risk controls, and a real-time monitoring dashboard.

## Features

- **Bring-your-own-data** — Ingest market data from any source via file loading (CSV/Parquet), REST POST, WebSocket streaming, or custom Python providers
- **Live order execution** — Equity orders, single-leg options, and multi-leg spreads via Public.com
- **Strategy framework** — Abstract base class with lifecycle management, event-driven signal generation, and order submission
- **Risk management** — 6 pre-trade checks, 2 post-trade checks, automatic trading halts, and configurable limits
- **Monitoring dashboard** — FastAPI-powered UI with real-time WebSocket updates, REST API, and system metrics
- **Event-driven architecture** — Async pub/sub event bus connecting all components with wildcard subscriptions

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      Dashboard (FastAPI)                          │
│            REST API ← EventBus → WebSocket (live updates)        │
├──────────────────────────────────────────────────────────────────┤
│                     Strategy Manager                              │
│        Register → Wire Events → Start/Stop Strategies            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Strategy (ABC)  ←  StrategyContext  →  RiskManager        │  │
│  │  on_quote / on_trade / on_bar → signals → submit_order     │  │
│  └────────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────┤
│                      Risk Manager                                 │
│  Pre-trade: position size, concentration, order value,           │
│             daily loss, open orders, symbol allow/block           │
│  Post-trade: portfolio drawdown, daily trade count               │
│  Halt: automatic trading halt on limit breach                    │
├──────────────────────────────────────────────────────────────────┤
│                        Event Bus                                  │
│  Channels: quote │ trade │ bar │ status │ order │ fill │ risk   │
│            strategy.signal │ execution.* │ system │ ...          │
├──────────────────────────────────────────────────────────────────┤
│                     Data & Execution Layer                        │
│  ┌─────────────────────────┐   ┌─────────────────────────┐     │
│  │  DataManager (BYOD)      │   │  Public.com Execution    │     │
│  │  ┌───────────────────┐  │   │  ┌───────────────────┐  │     │
│  │  │ DataProvider ABC  │  │   │  │ Equity Orders     │  │     │
│  │  │ CsvBarProvider    │  │   │  │ Option Orders     │  │     │
│  │  │ ParquetBarProvider│  │   │  │ Multi-leg Spreads │  │     │
│  │  │ Custom Providers  │  │   │  │ Portfolio Sync    │  │     │
│  │  ├───────────────────┤  │   │  │ Preflight Checks  │  │     │
│  │  │ REST Ingestion    │  │   │  └───────────────────┘  │     │
│  │  │ WS Ingestion      │  │   └─────────────────────────┘     │
│  │  └───────────────────┘  │                                    │
│  └─────────────────────────┘                                    │
├──────────────────────────────────────────────────────────────────┤
│                       Core Domain                                 │
│    Models: QuoteTick, TradeTick, Bar, Order, Position            │
│    Config │ Logging (structlog) │ Clock │ Enums                  │
└──────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
```

For Parquet file support:

```bash
pip install -e ".[parquet]"
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
│   └── enums.py             # Enumerations (Channel, OrderSide, etc.)
├── data/
│   ├── provider.py          # DataProvider abstract base class
│   ├── manager.py           # DataManager (provider orchestration)
│   ├── config.py            # DataConfig settings
│   ├── file_provider.py     # CsvBarProvider, ParquetBarProvider
│   └── ingestion_server.py  # REST + WebSocket ingestion endpoints
├── adapters/
│   ├── base.py              # ExecAdapter ABC
│   └── public_com/
│       ├── adapter.py       # Public.com execution adapter
│       ├── client.py        # Public.com API client
│       ├── parse.py         # Response parsers
│       └── config.py        # Public.com configuration
├── strategy/
│   ├── base.py              # Strategy abstract base class
│   ├── context.py           # StrategyContext (market data + order API)
│   ├── manager.py           # StrategyManager (lifecycle, event wiring)
│   └── examples/
│       └── sma_crossover.py # SMA crossover example strategy
├── risk/
│   ├── checks.py            # Pre-trade and post-trade check functions
│   ├── manager.py           # RiskManager (orchestrates checks, halts)
│   └── models.py            # RiskConfig, RiskState, RiskViolation
└── dashboard/
    ├── app.py               # FastAPI application and REST endpoints
    ├── ws.py                # WebSocket manager (DashboardWSManager)
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

### config.toml

```toml
[data]
ingestion_enabled = true           # Enable data ingestion endpoints
csv_directory = ""                 # Path to CSV files/directory (optional)
parquet_directory = ""             # Path to Parquet files/directory (optional)
replay_speed = 0.0                 # Replay speed multiplier (0 = instant)
max_bars_per_request = 10000       # Max bars per REST ingestion request

[public_com]
poll_interval = 2.0                # Order status poll interval (seconds)
portfolio_refresh = 30.0           # Portfolio sync interval (seconds)

[risk]
max_position_size = 1000.0         # Max shares per symbol
max_position_concentration = 0.10  # Max 10% in one name
max_order_value = 50000.0          # Max $ per order
daily_loss_limit = -5000.0         # Halt trading if daily P&L below this
max_open_orders = 20
max_daily_trades = 100
max_portfolio_drawdown = 0.15      # Halt on 15% drawdown

[dashboard]
host = "0.0.0.0"
port = 8080

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
- [Data Providers & Adapters](docs/adapters.md) — BYOD data providers + Public.com execution
- [Strategy Development](docs/strategies.md) — writing and running trading strategies
- [Risk Management](docs/risk-management.md) — risk checks, halts, configuration
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
