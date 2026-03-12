# Algo Trading Platform

A production-oriented live algorithmic trading platform built in Python. Event-driven architecture with real-time market data streaming from Alpaca (SIP/OPRA feeds) and a live monitoring dashboard.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Dashboard (FastAPI)                     │
│                    WebSocket ← EventBus → REST API            │
├──────────────────────────────────────────────────────────────┤
│                         Event Bus                             │
│  Channels: quote │ trade │ bar │ status │ order │ fill │ ... │
├──────────────────────────────────────────────────────────────┤
│                      Adapter Layer                            │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────┐   │
│  │  Alpaca Stock    │  │ Alpaca OPRA  │  │  Alpaca REST  │   │
│  │  Stream (SIP)    │  │ Stream (opt) │  │  Client       │   │
│  │  WebSocket/JSON  │  │ WS/msgpack   │  │  httpx        │   │
│  └────────┬─────────┘  └──────┬───────┘  └──────┬────────┘   │
│           └──────────┬────────┘                  │            │
│                      v                           v            │
│              AlpacaDataAdapter ──── InstrumentProvider        │
├──────────────────────────────────────────────────────────────┤
│                     Core Domain                               │
│     Models: QuoteTick, TradeTick, Bar, Order, Position       │
│     Config │ Logging (structlog) │ Clock │ Enums             │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Configure

Copy the environment template and add your Alpaca API credentials:

```bash
cp .env.example .env
# Edit .env with your Alpaca API key and secret
```

Edit `config.toml` to customize symbols, dashboard port, and feed settings.

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
- Stream connection status and message rates
- System metrics (msg/sec, memory, uptime)
- Subscription management (add/remove symbols)
- Event log with severity filtering

## Project Structure

```
src/trading_platform/
├── main.py                  # Entry point
├── core/
│   ├── events.py            # Async event bus (pub/sub)
│   ├── models.py            # Domain models (Pydantic)
│   ├── config.py            # Config management (.env + TOML)
│   ├── logging.py           # Structured logging (structlog)
│   ├── clock.py             # System clock
│   └── enums.py             # Enumerations
├── adapters/
│   ├── base.py              # DataAdapter / ExecAdapter ABCs
│   └── alpaca/
│       ├── adapter.py       # Unified Alpaca facade
│       ├── stream.py        # SIP + OPRA WebSocket clients
│       ├── client.py        # REST HTTP client
│       ├── provider.py      # Instrument provider
│       ├── parse.py         # Message parsers
│       └── config.py        # Alpaca configuration
├── strategy/
│   └── base.py              # Strategy base class
└── dashboard/
    ├── app.py               # FastAPI application
    ├── ws.py                # WebSocket manager
    └── static/index.html    # Dashboard UI
```

## Configuration Reference

### .env (secrets)

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca API key |
| `ALPACA_API_SECRET` | Alpaca API secret |

### config.toml

```toml
[alpaca]
feed = "sip"                    # sip or iex
stock_ws_url = "wss://stream.data.alpaca.markets/v2/sip"
options_ws_url = "wss://stream.data.alpaca.markets/v1beta1/opra"
base_url = "https://data.alpaca.markets"
trading_base_url = "https://api.alpaca.markets"

[dashboard]
host = "0.0.0.0"
port = 8080

[platform]
log_level = "INFO"
symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
```

## Testing

```bash
pytest tests/ -v
```

## Phase Roadmap

- [x] **Phase 1**: Core infrastructure (event bus, models, config, logging)
- [x] **Phase 2**: Alpaca market data (SIP stream, OPRA stream, REST client, dashboard)
- [ ] **Phase 3**: Public.com execution adapter
- [ ] **Phase 4**: Coinbase Advanced Trade adapter
- [ ] **Phase 5**: Strategy framework (base class, lifecycle, signal generation)
- [ ] **Phase 6**: Risk controls (position limits, order throttling, circuit breakers)
