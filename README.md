# Algo Trading Platform

A production-oriented live algorithmic trading platform built in Python. Event-driven architecture with real-time market data streaming (Alpaca SIP/OPRA), live order execution (Public.com), automated strategy management, risk controls, and a real-time monitoring dashboard.

## Features

- **Real-time market data** — SIP stock quotes/trades/bars and OPRA options data via Alpaca WebSocket streams
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
│                      Adapter Layer                                │
│  ┌────────────────────┐          ┌─────────────────────────┐     │
│  │  Alpaca Data        │          │  Public.com Execution    │     │
│  │  ┌──────────────┐  │          │  ┌───────────────────┐  │     │
│  │  │ SIP Stream   │  │          │  │ Equity Orders     │  │     │
│  │  │ (WS/JSON)    │  │          │  │ Option Orders     │  │     │
│  │  ├──────────────┤  │          │  │ Multi-leg Spreads │  │     │
│  │  │ OPRA Stream  │  │          │  │ Portfolio Sync    │  │     │
│  │  │ (WS/msgpack) │  │          │  │ Preflight Checks  │  │     │
│  │  ├──────────────┤  │          │  └───────────────────┘  │     │
│  │  │ REST Client  │  │          └─────────────────────────┘     │
│  │  │ (httpx)      │  │                                          │
│  │  └──────────────┘  │                                          │
│  └────────────────────┘                                          │
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

### 2. Configure

Copy the environment template and add your API credentials:

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca API key (market data) |
| `ALPACA_API_SECRET` | Alpaca API secret |
| `PUBLIC_API_SECRET` | Public.com API secret (execution) |
| `PUBLIC_ACCOUNT_ID` | Public.com account ID |

Edit `config.toml` to customize symbols, risk limits, dashboard port, and feed settings.

### 3. Run

```bash
trading-platform
# or
python -m trading_platform.main
```

Options:
- `--config path/to/config.toml` — custom config file
- `--log-level DEBUG` — override log level

### 4. Dashboard

Open `http://localhost:8080` in your browser. The dashboard shows:
- Real-time quotes with bid/ask/spread
- Live trade feed with uptick/downtick coloring
- Portfolio positions and P&L
- Active strategies and signals
- Risk state and violations
- Order management (submit, cancel)
- Stream connection status and message rates
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
├── adapters/
│   ├── base.py              # DataAdapter / ExecAdapter ABCs
│   ├── alpaca/
│   │   ├── adapter.py       # Unified Alpaca data facade
│   │   ├── stream.py        # SIP + OPRA WebSocket clients
│   │   ├── client.py        # REST HTTP client (bars, snapshots)
│   │   ├── provider.py      # Instrument provider
│   │   ├── parse.py         # Message parsers
│   │   └── config.py        # Alpaca configuration (frozen dataclass)
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
├── adapters.md              # Adapters guide
├── strategies.md            # Strategy development guide
├── risk-management.md       # Risk management guide
├── dashboard.md             # Dashboard guide
├── event-bus.md             # Event bus reference
├── api-reference.md         # API reference
└── examples/
    ├── basic_streaming.py       # Minimal Alpaca streaming example
    ├── place_equity_order.py    # Equity order placement
    ├── place_option_order.py    # Single-leg option order
    ├── place_spread_order.py    # Multi-leg spread order
    ├── custom_strategy.py       # Mean reversion strategy example
    ├── risk_configuration.py    # Risk controls configuration
    ├── portfolio_monitor.py     # Portfolio monitoring
    ├── event_listener.py        # Event bus subscription patterns
    └── backtest_data_collection.py  # Historical data collection
```

## Configuration Reference

### .env (secrets)

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca API key |
| `ALPACA_API_SECRET` | Alpaca API secret |
| `PUBLIC_API_SECRET` | Public.com API secret |
| `PUBLIC_ACCOUNT_ID` | Public.com account ID |

### config.toml

```toml
[alpaca]
feed = "sip"                    # "sip" (full) or "iex" (free)
stock_ws_url = "wss://stream.data.alpaca.markets/v2/sip"
options_ws_url = "wss://stream.data.alpaca.markets/v1beta1/opra"
rest_base_url = "https://data.alpaca.markets"
trading_base_url = "https://api.alpaca.markets"

[public_com]
poll_interval = 5.0             # order status poll interval (seconds)
portfolio_refresh = 30.0        # portfolio sync interval (seconds)

[risk]
max_position_size = 1000.0      # max shares per symbol
max_position_concentration = 0.20  # max 20% in one name
max_order_value = 50000.0       # max $ per order
daily_loss_limit = -5000.0      # halt trading if daily P&L below this
max_open_orders = 20
max_daily_trades = 100
max_portfolio_drawdown = 0.15   # halt on 15% drawdown

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
- [Adapters Guide](docs/adapters.md) — Alpaca data + Public.com execution adapters
- [Strategy Development](docs/strategies.md) — writing and running trading strategies
- [Risk Management](docs/risk-management.md) — risk checks, halts, configuration
- [Dashboard Guide](docs/dashboard.md) — UI features, REST API, WebSocket API
- [Event Bus Reference](docs/event-bus.md) — channels, payloads, subscription patterns
- [API Reference](docs/api-reference.md) — all public classes and methods
- [Example Scripts](docs/examples/) — 9 runnable examples

## Testing

```bash
pytest tests/ -v
```

## Phase Roadmap

- [x] **Phase 1**: Core infrastructure (event bus, models, config, logging)
- [x] **Phase 2**: Alpaca market data (SIP stream, OPRA stream, REST client, dashboard)
- [x] **Phase 3**: Public.com execution adapter (orders, portfolio, preflight)
- [ ] ~~**Phase 4**: Coinbase Advanced Trade adapter~~ *(deferred)*
- [x] **Phase 5**: Strategy framework (base class, context, manager, SMA crossover example)
- [x] **Phase 6**: Risk controls (pre-trade checks, post-trade checks, trading halts)
- [x] **Phase 7**: Documentation and examples
