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

## Phase 1b: Hot Path Optimizations

### Topic-Based EventBus Routing

The EventBus supports optional **topic-based subscriptions** to reduce unnecessary dispatching. Instead of delivering every event to every subscriber on a channel, subscribers can register for a specific topic (e.g., a symbol) and only receive matching events.

```python
# Broad subscription (receives all quotes — existing behavior)
await event_bus.subscribe("quote", on_any_quote)

# Topic-specific subscription (receives only AAPL quotes)
await event_bus.subscribe("quote", on_aapl_quote, topic="AAPL")

# Publishing with a topic reaches both topic-specific AND broad subscribers
await event_bus.publish("quote", quote_data, topic="AAPL")
```

This is fully backward compatible — existing code that doesn't use topics works unchanged. The `topic_filtered_count` metric tracks how many dispatches used topic filtering.

### Binary Serialization (MessagePack)

MessagePack is supported as an alternative to JSON for ingestion endpoints. MessagePack is a compact binary format that is faster to encode/decode and smaller on the wire.

**REST endpoints:**
- Send `Content-Type: application/x-msgpack` to submit MessagePack-encoded data
- Set `Accept: application/x-msgpack` to receive MessagePack responses
- JSON remains the default

**WebSocket ingestion (`/ws/data`):**
- Binary frames are parsed as MessagePack
- Text frames are parsed as JSON (existing behavior)

**Serialization module** (`trading_platform.data.serialization`):

```python
from trading_platform.data.serialization import Format, serialize, deserialize, detect_format

data = {"symbol": "AAPL", "price": 150.0}
packed = serialize(data, Format.MSGPACK)   # compact binary bytes
result = deserialize(packed, Format.MSGPACK)  # back to dict

fmt = detect_format("application/x-msgpack")  # Format.MSGPACK
fmt = detect_format("application/json")        # Format.JSON
```

### Lazy Deserialization

When `lazy_deserialize = true`, the MessageQueue stores raw bytes from `enqueue_raw()` and defers deserialization to the consumer. This moves parsing off the ingestion hot path entirely.

```toml
[performance]
default_serialization = "json"   # or "msgpack"
lazy_deserialize = true          # defer deserialization to consumer
```

### Connection Pooling

All API adapter clients (Public.com, Crypto, Options) use persistent HTTP connection pools via `httpx.AsyncClient` with configured limits:

- **max_connections = 20** — total concurrent connections per client
- **max_keepalive_connections = 10** — reusable keep-alive connections
- **timeout = 10s** — per-request timeout

This eliminates TCP + TLS handshake latency (~50–100ms) on repeated API calls by reusing existing connections. The pool is created at `connect()` and properly closed at `disconnect()`.

### Conditional Strategy Evaluation

A price-change gate on the Strategy base class skips evaluation when price hasn't moved enough since the last evaluation. This avoids running full strategy logic on trivial ticks.

```python
class MyStrategy(Strategy):
    def __init__(self, event_bus):
        super().__init__("my_strategy", event_bus, config={
            "min_price_change": "0.50",          # skip if price moved < $0.50
            "min_price_change_percent": "0.005",  # or < 0.5%
        })
```

- Either threshold triggering is sufficient (OR logic)
- Default is 0 for both (no gate — evaluate every tick)
- First tick for a symbol always evaluates
- Per-symbol tracking: AAPL gate is independent of MSFT gate
- **Does NOT affect** bracket orders, trailing stops, or scaled orders — they monitor price independently

**Metrics:**
- `evaluations_skipped` / `evaluations_run` per strategy
- `skip_rate_percent` property on each strategy

## uvloop (High-Performance Event Loop)

[uvloop](https://github.com/MagicStack/uvloop) is a drop-in replacement for the default `asyncio` event loop, built on top of libuv. It provides **2–4x faster** I/O operations and task scheduling compared to the default loop.

### How It Works

When installed and enabled, uvloop replaces the default asyncio event loop policy at startup — before any event loop is created. All existing async code runs unchanged on the faster loop.

### Installation

uvloop is an optional dependency (it doesn't work on Windows):

```bash
pip install algo-trading-platform[fast]
```

### Configuration

```toml
[performance]
use_uvloop = true   # default: true — set to false to use the default asyncio loop
```

### Startup Behavior

On startup the platform:

1. Reads `use_uvloop` from `config.toml` (defaults to `true`)
2. Attempts `import uvloop; uvloop.install()`
3. Logs which event loop is active:
   - `event loop: uvloop (high-performance)` — uvloop installed successfully
   - `event loop: default asyncio` — uvloop not available or disabled

### When to Disable

- **Windows** — uvloop doesn't support Windows; the fallback is automatic
- **Debugging** — Some debuggers work better with the default event loop
- **Compatibility** — If you encounter rare edge cases with third-party libraries

## Python 3.13 Free-Threaded Mode (Experimental)

Python 3.13 introduces experimental **free-threaded mode** (also known as "no-GIL" mode), which disables the Global Interpreter Lock. This allows true parallel execution of Python threads, which can benefit CPU-bound workloads like strategy evaluation, risk calculations, and greeks computation.

### How to Enable

Set the `PYTHON_GIL` environment variable before starting the platform:

```bash
PYTHON_GIL=0 trading-platform
```

Or in your shell profile:

```bash
export PYTHON_GIL=0
```

You can verify free-threaded mode is active:

```python
import sys
print(sys._is_gil_enabled())  # False when free-threaded mode is active
```

### Requirements

- **Python 3.13+** compiled with `--disable-gil` (the `python3.13t` free-threaded build)
- Standard CPython 3.13 builds include this as an experimental runtime flag

### Use Cases for Trading

| Workload | Benefit |
|----------|---------|
| Strategy evaluation across multiple symbols | Parallel `on_quote` / `on_bar` callbacks without GIL contention |
| Greeks computation | CPU-intensive Black-Scholes calculations can run on multiple threads |
| Risk checks | Portfolio-wide checks can run concurrently |
| Data deserialization | MessagePack / JSON parsing across threads |

### Important Caveats

- **Experimental** — This feature is not yet production-stable in Python 3.13. Test thoroughly before using in live trading.
- **C extension compatibility** — Some C extensions may not be thread-safe without the GIL. Verify that all dependencies work correctly.
- **Thread safety** — Code that relied on the GIL for implicit thread safety may need explicit locks.
- **Performance testing** — Free-threaded mode adds per-object locking overhead. Benchmark your specific workload to confirm it's faster than the default GIL-enabled mode.
- **Alternative to multiprocessing** — Free-threaded mode can replace multi-process worker architectures for CPU-bound parallelism, avoiding the overhead of IPC and memory duplication.

### Comparison with Other Parallelism Approaches

| Approach | CPU Parallelism | Memory Sharing | Complexity |
|----------|----------------|----------------|------------|
| asyncio (default) | No (cooperative) | Yes | Low |
| asyncio + uvloop | No (cooperative, faster I/O) | Yes | Low |
| multiprocessing | Yes | No (IPC needed) | High |
| Free-threaded (no-GIL) | Yes | Yes | Medium |

For I/O-bound workloads (API calls, WebSocket streaming, data ingestion), **uvloop** is the best choice. For CPU-bound workloads (strategy computation, risk calculations), **free-threaded mode** offers parallelism without the complexity of multiprocessing.

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
