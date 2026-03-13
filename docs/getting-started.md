# Getting Started

## Prerequisites

- **Python 3.12+**
- **Public.com account** with API access (for equity/options execution) — optional for data-only mode
- **Crypto exchange account** with API access (for crypto trading) — optional
- **pip** or a Python package manager

## Installation

### 1. Clone the Repository

```bash
git clone <repo-url> algo-trading-platform
cd algo-trading-platform
```

### 2. Install Dependencies

```bash
pip install -e ".[dev]"
```

This installs the platform package (`trading_platform`) along with all dependencies:

| Package | Purpose |
|---------|---------|
| `httpx` | REST API client |
| `fastapi` | Dashboard web framework |
| `uvicorn` | ASGI server |
| `structlog` | Structured logging |
| `python-dotenv` | Environment variable loading |
| `pydantic` / `pydantic-settings` | Configuration and model validation |
| `publicdotcom-py` | Public.com SDK |

Dev dependencies: `pytest`, `pytest-asyncio`.

## Configuration

### 3. Set Up Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Equity/Options execution (optional — platform runs without these)
PUBLIC_API_SECRET=your_public_api_secret
PUBLIC_ACCOUNT_ID=your_public_account_id

# Crypto execution (optional — activates CryptoExecAdapter)
CRYPTO_API_SECRET=your_crypto_api_secret
CRYPTO_ACCOUNT_ID=your_crypto_account_id

# Options execution (optional — use if separate from Public.com)
OPTIONS_API_SECRET=your_options_api_secret
OPTIONS_ACCOUNT_ID=your_options_account_id
```

Each adapter activates independently when its credentials are present. You can run any combination of equity, crypto, and options execution.

> **Security**: Never commit `.env` to version control. It's already in `.gitignore`.

### 4. Configure the Platform

Edit `config.toml` to customize behavior:

```toml
[data]
csv_directory = "/path/to/csvs"  # Load historical data from CSV files
replay_speed = 0.0               # 0 = instant, 1.0 = real-time

[platform]
log_level = "INFO"
symbols = ["AAPL", "MSFT", "GOOGL"]

[dashboard]
port = 8080

[risk]
max_position_size = 1000.0
max_order_value = 50000.0
daily_loss_limit = -5000.0

# Optional: Crypto trading pairs
[crypto]
trading_pairs = ["BTC-USD", "ETH-USD"]

# Optional: Options expiration management
[expiration]
auto_close_dte = 1
alert_dte = 7

# Optional: Greeks risk limits for options
[risk.greeks]
max_portfolio_delta = 500.0
max_portfolio_gamma = 100.0
max_daily_theta = -200.0
max_portfolio_vega = 1000.0
```

See [Configuration Reference](configuration.md) for all options.

## First Run

### 5. Start the Platform

```bash
trading-platform
```

Or with custom options:

```bash
trading-platform --config path/to/config.toml --log-level DEBUG
```

Or run directly:

```bash
python -m trading_platform.main
```

### What to Expect

On startup you'll see:

```
    _    _             _____              _ _
   / \  | | __ _  ___ |_   _| __ __ _  __| (_)_ __   __ _
  / _ \ | |/ _` |/ _ \  | || '__/ _` |/ _` | | '_ \ / _` |
 / ___ \| | (_| | (_) | | || | | (_| | (_| | | | | | (_| |
/_/   \_\_|\__, |\___/  |_||_|  \__,_|\__,_|_|_| |_|\__, |
           |___/                                     |___/
           P L A T F O R M   v0.3.0

[info] starting platform  dashboard_port=8080
[info] data manager started  providers=1
[info] public.com exec adapter configured
[info] crypto exec adapter configured
[info] options exec adapter configured
[info] order router registered  adapters=["stock", "crypto", "option"]
[info] risk manager initialized
[info] greeks provider initialized
[info] expiration manager started
[info] bracket order manager events wired
[info] trailing stop manager events wired
[info] scaled order manager events wired
[info] strategy manager initialized
[info] strategy manager events wired
[info] platform ready  dashboard=http://0.0.0.0:8080
```

Adapters activate independently based on available credentials:

```
[info] public.com exec adapter skipped (no credentials)
[info] crypto exec adapter skipped (no credentials)
[info] options exec adapter skipped (no credentials)
```

### 6. Access the Dashboard

Open [http://localhost:8080](http://localhost:8080) in your browser.

The dashboard displays:
- **Data providers** — Registered providers and connection status
- **Ingestion stats** — Bars, quotes, and trades received
- **System metrics** — Messages/sec, memory usage, uptime
- **Portfolio** — Positions and P&L (when execution adapter is connected)
- **Orders** — Active orders with cancel capability
- **Strategies** — Registered strategies with start/stop controls
- **Risk** — Current risk state and violation history

### 7. Verify Data Ingestion

**Ingest a bar via REST:**

```bash
curl -X POST http://localhost:8080/api/data/bars \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","open":185.0,"high":186.0,"low":184.5,"close":185.5,"volume":10000,"timestamp":"2024-01-15T09:30:00"}'
```

Expected response:

```json
{"ingested": 1}
```

**Check ingestion stats:**

```bash
curl http://localhost:8080/api/data/status
```

Expected response:

```json
{"bars_received": 1, "quotes_received": 0, "trades_received": 0, "providers": 0}
```

**Check platform status:**

```bash
curl http://localhost:8080/api/status
```

**Check portfolio (when exec adapter is connected):**

```bash
curl http://localhost:8080/api/portfolio
```

**Check trailing stops:**

```bash
curl http://localhost:8080/api/trailing-stops
```

**Check scaled orders:**

```bash
curl http://localhost:8080/api/scaled-orders
```

**Check bracket orders:**

```bash
curl http://localhost:8080/api/brackets
```

**Check portfolio greeks (when options adapter is connected):**

```bash
curl http://localhost:8080/api/options/portfolio-greeks
```

**Check option expirations:**

```bash
curl http://localhost:8080/api/options/expirations
```

## Running Tests

```bash
pytest tests/ -v
```

Tests cover:
- EventBus pub/sub and wildcard subscriptions
- Domain model serialization
- DataManager provider registration and streaming
- CSV bar provider loading and replay
- REST and WebSocket data ingestion
- Public.com, crypto, and options adapter integration
- Order routing across asset classes
- Bracket orders, trailing stops, and scaled orders
- Options strategy builder and validator
- Greeks provider caching and aggregation
- Expiration management and auto-close
- Strategy lifecycle and manager
- Risk checks, greeks risk checks, and violations
- Dashboard API endpoints

## Stopping the Platform

Press `Ctrl+C` for graceful shutdown. The platform will:

1. Stop all active strategies
2. Unwire event subscriptions (strategies, brackets, trailing stops, scaled orders)
3. Stop expiration manager
4. Close WebSocket connections
5. Disconnect all execution adapters (equity, crypto, options) via OrderRouter
6. Stop DataManager and disconnect all providers
7. Stop the dashboard server

## Next Steps

- [Configuration Reference](configuration.md) — Tune all settings including crypto, options, and greeks limits
- [Data Providers & Adapters](adapters.md) — Bring your own data sources, set up crypto and options execution
- [Strategies Guide](strategies.md) — Write your first trading strategy
- [Risk Management](risk-management.md) — Configure risk controls and greeks-aware checks
- [Dashboard Guide](dashboard.md) — Explore all REST and WebSocket endpoints
- [Event Bus Reference](event-bus.md) — Channels, payloads, and subscription patterns
- [API Reference](api-reference.md) — All public classes and methods
