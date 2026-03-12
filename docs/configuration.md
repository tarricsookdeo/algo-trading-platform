# Configuration Reference

The platform uses two configuration sources: `.env` for secrets and `config.toml` for all other settings. Pydantic Settings handles loading and validation.

## Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `ALPACA_API_KEY` | Yes | Alpaca API key for market data access |
| `ALPACA_API_SECRET` | Yes | Alpaca API secret |
| `PUBLIC_API_SECRET` | No | Public.com API secret key for order execution |
| `PUBLIC_ACCOUNT_ID` | No | Public.com account identifier |

The platform starts in **data-only mode** if `PUBLIC_API_SECRET` or `PUBLIC_ACCOUNT_ID` are not set. Market data streaming and the dashboard work without execution credentials.

## Config File (`config.toml`)

### `[alpaca]` — Market Data Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `feed` | string | `"sip"` | Data feed: `"sip"` (full market, requires subscription) or `"iex"` (free tier, IEX-only) |
| `base_url` | string | `"https://data.alpaca.markets"` | Alpaca data REST API base URL |
| `trading_base_url` | string | `"https://api.alpaca.markets"` | Alpaca trading API base URL |
| `stock_ws_url` | string | `"wss://stream.data.alpaca.markets/v2/sip"` | Stock WebSocket stream URL (change to `/v2/iex` for IEX feed) |
| `options_ws_url` | string | `"wss://stream.data.alpaca.markets/v1beta1/opra"` | Options WebSocket stream URL (OPRA feed) |

### `[public_com]` — Execution Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `poll_interval` | float | `2.0` | Order status polling interval in seconds |
| `portfolio_refresh` | float | `30.0` | Portfolio sync interval in seconds |

### `[risk]` — Risk Management Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_position_size` | float | `1000.0` | Maximum shares/contracts per position |
| `max_position_concentration` | float | `0.10` | Maximum single-position value as fraction of portfolio (10%) |
| `max_order_value` | float | `50000.0` | Maximum dollar value per order |
| `daily_loss_limit` | float | `-5000.0` | Daily P&L floor — triggers trading halt when breached |
| `max_open_orders` | int | `20` | Maximum concurrent open orders |
| `max_daily_trades` | int | `100` | Maximum trades per day (post-trade alert) |
| `max_portfolio_drawdown` | float | `0.15` | Maximum drawdown from peak (15%) — triggers trading halt |
| `allowed_symbols` | list | `[]` | Symbol allowlist (empty = allow all) |
| `blocked_symbols` | list | `[]` | Symbol blocklist (checked before allowlist) |

### `[dashboard]` — Dashboard Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"0.0.0.0"` | Dashboard bind address |
| `port` | int | `8080` | Dashboard port |

### `[platform]` — General Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `log_level` | string | `"INFO"` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `symbols` | list | `["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]` | Symbols to subscribe on startup |

## Environment Variable Precedence

Environment variables (from `.env` or the shell) take precedence over `config.toml` values for fields that overlap. The Pydantic Settings loader processes them in order:

1. `.env` file (loaded via `python-dotenv`)
2. `config.toml` (loaded via `load_toml()`)
3. Pydantic defaults

## Example Configurations

### Conservative Profile

For small accounts or initial testing:

```toml
[risk]
max_position_size = 100.0
max_position_concentration = 0.05
max_order_value = 5000.0
daily_loss_limit = -500.0
max_open_orders = 5
max_daily_trades = 20
max_portfolio_drawdown = 0.05

[platform]
symbols = ["AAPL", "MSFT"]
```

### Moderate Profile

Balanced risk for active trading:

```toml
[risk]
max_position_size = 500.0
max_position_concentration = 0.10
max_order_value = 25000.0
daily_loss_limit = -2500.0
max_open_orders = 15
max_daily_trades = 75
max_portfolio_drawdown = 0.10

[platform]
symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
```

### Aggressive Profile

For larger accounts with higher risk tolerance:

```toml
[risk]
max_position_size = 5000.0
max_position_concentration = 0.25
max_order_value = 100000.0
daily_loss_limit = -25000.0
max_open_orders = 50
max_daily_trades = 500
max_portfolio_drawdown = 0.20

[platform]
symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "SPY", "QQQ", "IWM"]
```

### Paper Trading / Data-Only Mode

To run without execution (omit Public.com credentials):

```bash
# .env — only Alpaca credentials
ALPACA_API_KEY=your_key
ALPACA_API_SECRET=your_secret
```

```toml
# config.toml
[alpaca]
feed = "iex"  # Free tier for development

[platform]
log_level = "DEBUG"
symbols = ["AAPL"]
```

## CLI Options

The `trading-platform` command accepts:

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to `config.toml` (default: `config.toml` in current directory) |
| `--log-level LEVEL` | Override log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
