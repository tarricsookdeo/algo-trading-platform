# Configuration Reference

The platform uses two configuration sources: `.env` for secrets and `config.toml` for all other settings. Pydantic Settings handles loading and validation.

## Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `PUBLIC_API_SECRET` | No | Public.com API secret key for equity/options execution |
| `PUBLIC_ACCOUNT_ID` | No | Public.com account identifier |
| `CRYPTO_API_SECRET` | No | Crypto exchange API secret key |
| `CRYPTO_ACCOUNT_ID` | No | Crypto exchange account identifier |
| `OPTIONS_API_SECRET` | No | Options API secret (if separate from Public.com) |
| `OPTIONS_ACCOUNT_ID` | No | Options account identifier |

The platform starts in **data-only mode** if no execution credentials are set. Data ingestion, strategies, and the dashboard work without execution credentials. Each adapter activates independently when its credentials are present.

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

### `[crypto]` — Crypto Trading Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trading_pairs` | list | `["BTC-USD", "ETH-USD"]` | Crypto trading pairs to enable |
| `poll_interval` | float | `2.0` | Order status polling interval in seconds |
| `portfolio_refresh` | float | `30.0` | Portfolio sync interval in seconds |

### `[options]` — Options Trading Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `poll_interval` | float | `2.0` | Order status polling interval in seconds |
| `portfolio_refresh` | float | `30.0` | Portfolio sync interval in seconds |

### `[trailing_stop]` — Trailing Stop Defaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| (No required settings) | — | — | Defaults are built into `TrailingStopManager`; override here if needed |

### `[expiration]` — Options Expiration Management

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_close_dte` | int | `1` | Auto-close option positions at this DTE |
| `alert_dte` | int | `7` | Publish alert when DTE reaches this threshold |
| `roll_enabled` | bool | `false` | Enable automatic rolling to a later expiration |
| `roll_target_dte` | int | `30` | Target DTE when rolling positions |
| `check_interval_seconds` | float | `60.0` | How often to check expirations (seconds) |

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

### `[risk.greeks]` — Greeks Risk Limits

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_portfolio_delta` | float | `500.0` | Maximum absolute portfolio delta |
| `max_portfolio_gamma` | float | `100.0` | Maximum absolute portfolio gamma |
| `max_daily_theta` | float | `-200.0` | Maximum daily theta decay (negative value) |
| `max_portfolio_vega` | float | `1000.0` | Maximum absolute portfolio vega |
| `max_position_delta` | float | `None` | Per-position delta limit (optional) |
| `max_position_gamma` | float | `None` | Per-position gamma limit (optional) |
| `max_position_vega` | float | `None` | Per-position vega limit (optional) |
| `greeks_refresh_interval_seconds` | float | `30.0` | Greeks cache refresh interval |

### `[performance]` — Performance Tuning

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message_queue_size` | int | `50000` | Maximum messages in the internal queue |
| `message_queue_mode` | string | `"lossy"` | Queue full behavior: `"lossy"` (drop oldest) or `"lossless"` (back-pressure) |
| `consumer_batch_size` | int | `100` | Max messages consumed per batch |
| `consumer_flush_interval_ms` | int | `10` | Max wait time before flushing an incomplete batch (ms) |
| `dedup_quotes_in_batch` | bool | `true` | Deduplicate quotes per symbol within each batch (keeps latest) |
| `default_serialization` | string | `"json"` | Default serialization format: `"json"` or `"msgpack"` |
| `lazy_deserialize` | bool | `false` | Defer deserialization to consumer (stores raw bytes in queue) |

### `[dashboard]` — Dashboard Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"0.0.0.0"` | Dashboard bind address |
| `port` | int | `8080` | Dashboard port |
| `update_interval_ms` | int | `100` | Dashboard throttler flush interval in milliseconds |
| `max_trades_per_flush` | int | `50` | Maximum trade events per throttled flush |

### `[platform]` — General Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `log_level` | string | `"INFO"` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `symbols` | list | `["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]` | Default symbol list for strategies |

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

### Crypto Trading

24/7 crypto trading with custom pairs:

```toml
[crypto]
trading_pairs = ["BTC-USD", "ETH-USD", "SOL-USD"]
poll_interval = 1.0
portfolio_refresh = 15.0

[risk]
max_order_value = 10000.0
daily_loss_limit = -2000.0
```

### Options Trading with Greeks Limits

Active options trading with greeks-aware risk controls:

```toml
[options]
poll_interval = 1.0
portfolio_refresh = 15.0

[expiration]
auto_close_dte = 1
alert_dte = 7
roll_enabled = true
roll_target_dte = 30

[risk]
max_order_value = 25000.0

[risk.greeks]
max_portfolio_delta = 300.0
max_portfolio_gamma = 50.0
max_daily_theta = -100.0
max_portfolio_vega = 500.0
```

### High-Throughput Performance Tuning

For high-frequency data ingestion with dashboard throttling:

```toml
[performance]
message_queue_size = 100000
message_queue_mode = "lossy"
consumer_batch_size = 200
consumer_flush_interval_ms = 5
dedup_quotes_in_batch = true
default_serialization = "msgpack"   # Use MessagePack for compact binary encoding
lazy_deserialize = true             # Defer deserialization to consumer

[dashboard]
host = "0.0.0.0"
port = 8080
update_interval_ms = 200      # Slower dashboard updates to reduce WS overhead
max_trades_per_flush = 20     # Cap trades per flush for large volumes
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

## CLI Options

The `trading-platform` command accepts:

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to `config.toml` (default: `config.toml` in current directory) |
| `--log-level LEVEL` | Override log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
