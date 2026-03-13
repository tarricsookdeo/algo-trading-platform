# Configuration Reference

The platform uses two configuration sources: `.env` for secrets and `config.toml` for all other settings. Pydantic Settings handles loading and validation.

## Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `PUBLIC_API_SECRET` | No | Public.com API secret key for order execution |
| `PUBLIC_ACCOUNT_ID` | No | Public.com account identifier |

The platform starts in **data-only mode** if `PUBLIC_API_SECRET` or `PUBLIC_ACCOUNT_ID` are not set. Data ingestion, strategies, and the dashboard work without execution credentials.

## Config File (`config.toml`)

### `[data]` — Data Ingestion Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ingestion_enabled` | bool | `true` | Enable REST and WebSocket data ingestion endpoints |
| `csv_directory` | string | `""` | Path to CSV file or directory (loads all `*.csv` files if directory) |
| `replay_speed` | float | `0.0` | Replay speed multiplier for file providers (`0` = instant, `1.0` = real-time, `2.0` = 2x) |
| `max_bars_per_request` | int | `10000` | Maximum bars per REST ingestion request |

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
| `symbols` | list | `["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]` | Default symbol list for strategies |

### `[crypto]` — Crypto Trading Settings
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trading_pairs` | list | `["BTC-USD", "ETH-USD"]` | Supported crypto trading pairs |
| `poll_interval` | float | `2.0` | Order status polling interval in seconds |
| `portfolio_refresh` | float | `30.0` | Portfolio sync interval in seconds |

### `[options]` — Options Trading Settings
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `poll_interval` | float | `2.0` | Order status polling interval in seconds |
| `portfolio_refresh` | float | `30.0` | Portfolio sync interval in seconds |

### `[options.expiration]` — Expiration Management Settings
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_close_dte` | int | `1` | Auto-close positions at N DTE to avoid assignment |
| `alert_dte` | int | `7` | Send alert when position reaches N DTE |
| `roll_enabled` | bool | `false` | Attempt to roll position to next expiration on auto-close |
| `roll_target_dte` | int | `30` | Target DTE for rolled positions |
| `check_interval_seconds` | float | `60.0` | How often to check DTE on positions |

### `[risk.greeks]` — Greeks Risk Limits
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_portfolio_delta` | float | `500.0` | Maximum absolute portfolio delta |
| `max_portfolio_gamma` | float | `100.0` | Maximum absolute portfolio gamma |
| `max_daily_theta` | float | `-200.0` | Maximum daily theta decay (negative = max loss from decay) |
| `max_portfolio_vega` | float | `1000.0` | Maximum absolute portfolio vega |
| `greeks_refresh_interval_seconds` | float | `30.0` | How often to refresh greeks from broker |

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

### CSV Replay Mode

Replay historical data from CSV files:

```toml
[data]
csv_directory = "/path/to/your/csvs"
replay_speed = 1.0  # Real-time replay

[platform]
log_level = "DEBUG"
```

### REST Ingestion Mode

Accept data from external systems via REST API:

```toml
[data]
ingestion_enabled = true

[dashboard]
port = 8080

[platform]
log_level = "INFO"
```

### Data-Only Mode (No Execution)

To run without execution (omit Public.com credentials):

```bash
# .env — no credentials needed for data-only mode
```

```toml
# config.toml
[data]
csv_directory = "/path/to/csvs"

[platform]
log_level = "DEBUG"
```

### Options + Greeks Risk Profile

```toml
[options]
poll_interval = 2.0
portfolio_refresh = 15.0

[options.expiration]
auto_close_dte = 1
alert_dte = 7
roll_enabled = true
roll_target_dte = 30

[risk.greeks]
max_portfolio_delta = 500.0
max_portfolio_gamma = 100.0
max_daily_theta = -200.0
max_portfolio_vega = 1000.0
```

### Crypto Trading Profile

```toml
[crypto]
trading_pairs = ["BTC-USD", "ETH-USD", "SOL-USD"]
poll_interval = 2.0
portfolio_refresh = 15.0

[risk]
max_position_size = 5000.0
max_order_value = 100000.0
```

## CLI Options

The `trading-platform` command accepts:

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to `config.toml` (default: `config.toml` in current directory) |
| `--log-level LEVEL` | Override log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
