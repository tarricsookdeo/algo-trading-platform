# Dashboard Guide

## Overview

The dashboard is a FastAPI web application that provides real-time monitoring of the trading platform. It includes a static HTML/JavaScript frontend and exposes both REST and WebSocket APIs.

Access the dashboard at `http://localhost:8080` (configurable via `[dashboard]` in `config.toml`).

## Dashboard Panels

The web UI displays:

| Panel | Description |
|-------|-------------|
| **Quotes** | Real-time bid/ask/spread for active symbols |
| **Trade Feed** | Live trade stream with uptick/downtick coloring |
| **Data Providers** | Registered data providers and connection status |
| **Ingestion Stats** | Bars, quotes, and trades received from all sources |
| **System Metrics** | Messages/sec, total messages, memory usage, uptime, connected clients |
| **Event Log** | Recent platform events with severity filtering |
| **Portfolio** | Current positions with quantities and P&L |
| **Orders** | Active orders with cancel buttons |
| **Strategies** | Registered strategies with state, P&L, and start/stop controls |
| **Risk** | Current risk state, limits, and violation history |
| **P&L** | Daily and cumulative P&L, per-strategy breakdown |

## REST API Reference

### `GET /api/status`

Platform status and data ingestion stats.

**Response:**

```json
{
  "status": "running",
  "total_events": 45231,
  "events_per_second": 152.3,
  "subscribers": 12,
  "data_providers": [
    {"name": "csv:/data/bars.csv", "connected": true}
  ],
  "ingestion": {
    "bars_received": 500,
    "quotes_received": 1000,
    "trades_received": 200,
    "providers": 1
  }
}
```

The `data_providers` and `ingestion` fields are included when a `DataManager` is configured.

---

### `GET /api/portfolio`

Current positions and account information.

**Response:**

```json
{
  "positions": [
    {
      "symbol": "AAPL",
      "quantity": 100.0,
      "avg_entry_price": 150.25,
      "market_value": 15200.0,
      "unrealized_pnl": 175.0,
      "side": "long"
    }
  ],
  "account": {
    "buying_power_cash": 50000.0,
    "buying_power_margin": 100000.0,
    "equity": 150000.0
  }
}
```

Returns empty positions and account if no execution adapter is configured.

---

### `GET /api/orders`

Tracked orders.

**Response:**

```json
{
  "orders": [
    {
      "order_id": "abc-123",
      "status": "tracked"
    }
  ]
}
```

---

### `POST /api/orders/{order_id}/cancel`

Cancel an order.

**Example:** `POST /api/orders/abc-123/cancel`

**Response (success):**

```json
{
  "status": "cancel_requested",
  "order_id": "abc-123"
}
```

**Response (error):**

```json
{
  "error": "Order not found"
}
```

---

### `GET /api/strategies`

Registered strategies with state and metrics.

**Response:**

```json
{
  "strategies": [
    {
      "strategy_id": "sma-crossover",
      "state": "active",
      "trades_executed": 15,
      "wins": 9,
      "losses": 6,
      "pnl": 1250.50,
      "signals": []
    }
  ]
}
```

---

### `POST /api/strategies/{strategy_id}/start`

Start a registered strategy.

**Example:** `POST /api/strategies/sma-crossover/start`

**Response:**

```json
{
  "status": "started",
  "strategy_id": "sma-crossover"
}
```

---

### `POST /api/strategies/{strategy_id}/stop`

Stop a running strategy.

**Example:** `POST /api/strategies/sma-crossover/stop`

**Response:**

```json
{
  "status": "stopped",
  "strategy_id": "sma-crossover"
}
```

---

### `GET /api/risk`

Current risk management state.

**Response:**

```json
{
  "risk": {
    "is_halted": false,
    "halt_reason": "",
    "daily_pnl": -1200.0,
    "daily_trade_count": 42,
    "portfolio_value": 98000.0,
    "portfolio_peak": 100000.0,
    "open_order_count": 3,
    "max_position_size": 1000.0,
    "max_order_value": 50000.0,
    "daily_loss_limit": -5000.0,
    "max_portfolio_drawdown": 0.15
  }
}
```

---

### `GET /api/risk/violations`

Risk violation history.

**Response:**

```json
{
  "violations": [
    {
      "check_name": "pre_trade",
      "message": "Order value $75,000.00 exceeds limit $50,000.00",
      "order_id": "order-456",
      "symbol": "TSLA",
      "timestamp": "2026-03-12T14:30:00Z",
      "data": {}
    }
  ]
}
```

---

### `GET /api/pnl`

Profit and loss summary.

**Response:**

```json
{
  "daily_pnl": -1200.0,
  "cumulative_pnl": 5800.0,
  "strategy_pnl": {
    "sma-crossover": 3200.0,
    "mean-reversion": 2600.0
  }
}
```

---

### Data Ingestion Endpoints

The platform exposes REST and WebSocket endpoints for external data ingestion. These are automatically mounted when `data_manager` is provided to `create_app()`.

See [Data Providers & Adapters](adapters.md#rest--websocket-ingestion) for full endpoint documentation, including:

- `POST /api/data/bars` — Ingest bar data (single or batch)
- `POST /api/data/quotes` — Ingest quote data
- `POST /api/data/trades` — Ingest trade data
- `GET /api/data/status` — Ingestion statistics
- `GET /api/data/providers` — Provider status
- `WebSocket /ws/data` — Streaming ingestion

---

## WebSocket API

Connect to `ws://localhost:8080/ws` for real-time updates.

### Connection

```javascript
const ws = new WebSocket("ws://localhost:8080/ws");

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    console.log(msg.type, msg.data);
};
```

### Message Format

All messages follow this structure:

```json
{
  "type": "<message_type>",
  "data": { ... }
}
```

### Message Types

| Type | Source | Description |
|------|--------|-------------|
| `quote` | `Channel.QUOTE` | Real-time quote update |
| `trade` | `Channel.TRADE` | Real-time trade update |
| `bar` | `Channel.BAR` | Bar (candle) update |
| `system` | `Channel.SYSTEM` | System event (startup, shutdown, errors) |
| `order` | `Channel.ORDER` | Order status change |
| `fill` | `Channel.FILL` | Order fill |
| `position` | `Channel.POSITION` | Position update |
| `metrics` | Internal | System metrics (broadcast every 2 seconds) |

### Metrics Message

Broadcast every 2 seconds:

```json
{
  "type": "metrics",
  "data": {
    "uptime_seconds": 3600.5,
    "messages_per_second": 150.2,
    "total_messages": 540720,
    "active_subscribers": 12,
    "memory_mb": 85.3,
    "connected_clients": 2,
    "timestamp": "2026-03-12T14:30:00Z"
  }
}
```

## Customizing the Dashboard

The dashboard UI is served from `src/trading_platform/dashboard/static/index.html`. You can modify this file to customize the layout, add new panels, or change styling.

The backend is a standard FastAPI application created by `create_app()`. To add new endpoints:

```python
from trading_platform.dashboard.app import create_app

app, ws_manager = create_app(event_bus, data_manager=data_manager, ...)

@app.get("/api/custom")
async def custom_endpoint():
    return {"custom": "data"}
```
