# Performance Guide

## Overview

Performance Phase 1 introduces an internal message queue, dashboard throttling, batch ingestion endpoints, and real-time performance metrics. These components work together to sustain high-throughput data ingestion without overwhelming the EventBus or dashboard WebSocket clients.

## Architecture

```
Data Sources → DataManager → MessageQueue → Consumer → EventBus → Subscribers
                                                                  ↓
                                                          DashboardWSManager
                                                                  ↓
                                                        DashboardThrottler
                                                                  ↓
                                                        WebSocket Clients
```

## Internal Message Queue

The `MessageQueue` (`core/message_queue.py`) is an async bounded queue that decouples data ingestion from event processing.

### How It Works

1. **Ingestion** — `DataManager.publish_bar/quote/trade()` tags each message with `_channel` metadata and enqueues it
2. **Consumer** — A background `asyncio.Task` drains the queue in batches, publishing each message to the EventBus
3. **Deduplication** — When enabled, the consumer deduplicates quotes within each batch, keeping only the latest per symbol

### Modes

| Mode | Behavior When Full | Use Case |
|------|-------------------|----------|
| `lossy` | Drops the oldest message to make room | Real-time trading where stale data is worse than missing data |
| `lossless` | Blocks the enqueue call until space is available | Backtesting or replay where every message matters |

### Configuration

```toml
[performance]
message_queue_size = 50000         # Queue capacity
message_queue_mode = "lossy"       # "lossy" or "lossless"
consumer_batch_size = 100          # Messages per batch
consumer_flush_interval_ms = 10    # Max wait before flushing incomplete batch
dedup_quotes_in_batch = true       # Deduplicate quotes per symbol in each batch
```

### Tuning Tips

- **High-frequency feeds**: Increase `message_queue_size` and `consumer_batch_size`. Enable `dedup_quotes_in_batch` to collapse rapid quote updates.
- **Low-latency trading**: Use smaller `consumer_batch_size` (10–50) and lower `consumer_flush_interval_ms` (5) to reduce processing delay.
- **Backtesting**: Use `lossless` mode to ensure no messages are dropped. Increase queue size to absorb bursts.

## Dashboard Throttling

The `DashboardThrottler` (`dashboard/throttler.py`) buffers high-frequency market data events and flushes them to WebSocket clients at a fixed interval.

### How It Works

1. **Buffer** — Incoming quote, trade, and bar events are buffered in memory
2. **Dedup** — Quotes and bars are deduplicated by symbol (latest wins)
3. **Cap** — Trade events are capped at `max_trades_per_flush`
4. **Flush** — At each interval, all buffered events are sent as a single batch message

### Configuration

```toml
[dashboard]
update_interval_ms = 100           # Flush interval (ms)
max_trades_per_flush = 50          # Max trade events per flush
```

### Impact

Without throttling, a feed of 5,000 quotes/sec would generate 5,000 WebSocket broadcasts per second. With throttling at 100 ms intervals, this becomes ~10 batch messages per second, each containing the latest quote per symbol.

## Batch Ingestion Endpoints

Three batch REST endpoints accept arrays of market data in a single request:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data/bars/batch` | POST | Ingest up to `max_bars_per_request` bars |
| `/api/data/quotes/batch` | POST | Ingest a batch of quotes |
| `/api/data/trades/batch` | POST | Ingest a batch of trades |

The WebSocket ingestion endpoint (`/ws/data`) also accepts JSON arrays for batch frame processing.

### Example

```bash
curl -X POST http://localhost:8080/api/data/bars/batch \
  -H "Content-Type: application/json" \
  -d '[
    {"symbol":"AAPL","open":185.0,"high":186.0,"low":184.5,"close":185.5,"volume":10000},
    {"symbol":"MSFT","open":420.0,"high":421.0,"low":419.0,"close":420.5,"volume":8000}
  ]'
```

## Performance Metrics

The `PerformanceMetrics` class (`core/metrics.py`) tracks platform throughput and latency in real time.

### Tracked Metrics

| Metric | Description |
|--------|-------------|
| `messages_received` | Total messages ingested |
| `messages_processed` | Total messages published to EventBus |
| `ingestion_rate` | Messages received per second (rolling 5s window) |
| `processing_rate` | Messages processed per second (rolling 5s window) |
| `queue_depth` | Current message queue depth |
| `queue_drops` | Total messages dropped (lossy mode) |
| `avg_latency_ms` | Average enqueue-to-publish latency |
| `max_latency_ms` | Maximum enqueue-to-publish latency |
| `dashboard_broadcasts` | Total dashboard broadcasts |
| `dashboard_broadcast_rate` | Broadcasts per second (rolling 5s window) |

### REST Endpoint

```
GET /api/metrics
```

Returns a JSON object with all performance metrics plus message queue stats (depth, drop count, consumer dequeue count).

### Dashboard Display

The dashboard UI displays live performance metrics including messages per second, total messages, memory usage, and connected clients. The metrics panel updates every 2 seconds via WebSocket.

## Monitoring and Troubleshooting

### High Queue Depth

If `queue_depth` is consistently high, the consumer can't keep up with ingestion:

- Increase `consumer_batch_size` to process more messages per cycle
- Decrease `consumer_flush_interval_ms` to flush batches sooner
- Enable `dedup_quotes_in_batch` to reduce redundant processing
- Check subscriber callbacks for slow operations

### High Drop Count

If `queue_drops` is increasing in lossy mode:

- Increase `message_queue_size` to absorb larger bursts
- Switch to `lossless` mode if every message matters (at the cost of back-pressure)
- Reduce ingestion rate at the source

### High Dashboard Latency

If the dashboard feels sluggish:

- Increase `update_interval_ms` to reduce WebSocket overhead (at the cost of update frequency)
- Decrease `max_trades_per_flush` to keep batch messages smaller
- Check browser DevTools for WebSocket frame size
