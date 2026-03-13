# Getting Started

## Prerequisites

- **Python 3.12+**
- **Public.com account** with API access (for order execution) — optional for data-only mode
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


```bash
```

## Configuration

### 3. Set Up Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Required for order execution (optional — platform runs without these)
PUBLIC_API_SECRET=your_public_api_secret
PUBLIC_ACCOUNT_ID=your_public_account_id
```

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
           P L A T F O R M   v0.2.0

[info] starting platform  dashboard_port=8080
[info] data manager started  providers=1
[info] public.com exec adapter configured
[info] risk manager initialized
[info] strategy manager initialized
[info] strategy manager events wired
[info] platform ready  dashboard=http://0.0.0.0:8080
```

If Public.com credentials are not set, the platform runs in **data-only mode**:

```
[info] public.com exec adapter skipped (no credentials)
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
- Public.com adapter integration
- Strategy lifecycle and manager
- Risk checks and violations
- Dashboard API endpoints

## Stopping the Platform

Press `Ctrl+C` for graceful shutdown. The platform will:

1. Stop all active strategies
2. Unwire event subscriptions
3. Close WebSocket connections
4. Disconnect from Public.com
5. Stop DataManager and disconnect all providers
6. Stop the dashboard server

## Next Steps

- [Configuration Reference](configuration.md) — Tune all settings
- [Data Providers & Adapters](adapters.md) — Bring your own data sources
- [Strategies Guide](strategies.md) — Write your first trading strategy
- [Risk Management](risk-management.md) — Configure risk controls
