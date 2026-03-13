"""Backtest data collection example.

Demonstrates how to create CSV files in the platform's expected format
and load them using CsvBarProvider for backtesting. Also shows how to
send bars to a running platform instance via the REST ingestion API.

Demonstrates:
- Creating CSV files in the expected format
- Loading CSVs with CsvBarProvider
- Streaming bars through the DataManager
- Sending historical bars to a live platform via REST

Prerequisites:
    - pip install -e .
    - Optional: pip install httpx (for REST ingestion example)

Usage:
    python docs/examples/backtest_data_collection.py
"""

from __future__ import annotations

import asyncio
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.data import CsvBarProvider, DataConfig, DataManager


def generate_sample_csv(filepath: Path, symbol: str, num_bars: int = 100) -> None:
    """Generate a sample CSV file with synthetic OHLCV data."""
    filepath.parent.mkdir(parents=True, exist_ok=True)

    price = 150.0 + random.random() * 100
    start_time = datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc)

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        for i in range(num_bars):
            ts = start_time + timedelta(minutes=i)
            change = random.uniform(-1.0, 1.0)
            o = round(price, 2)
            h = round(price + abs(change) + random.uniform(0, 0.5), 2)
            l = round(price - abs(change) - random.uniform(0, 0.5), 2)
            c = round(price + change, 2)
            v = random.randint(1000, 50000)
            writer.writerow([ts.isoformat(), symbol, o, h, l, c, v])
            price = c

    print(f"  Generated {num_bars} bars -> {filepath}")


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.backtest_data")

    symbols = ["AAPL", "MSFT", "TSLA"]
    output_dir = Path("backtest_data")

    # ── Step 1: Generate sample CSV files ──────────────────────────────
    print("Generating sample CSV data...")
    for symbol in symbols:
        filepath = output_dir / f"{symbol}_1min.csv"
        generate_sample_csv(filepath, symbol, num_bars=200)

    # ── Step 2: Load CSVs using CsvBarProvider and DataManager ─────────
    print("\nLoading CSVs into the platform...")
    event_bus = EventBus()
    bar_count = 0

    async def on_bar(channel: str, event: dict) -> None:
        nonlocal bar_count
        bar_count += 1
        if bar_count <= 5:
            sym = event.get("symbol", "?") if isinstance(event, dict) else event.symbol
            close = event.get("close", 0) if isinstance(event, dict) else event.close
            print(f"  [BAR] {sym}: close={close}")
        elif bar_count == 6:
            print("  [BAR] ... (suppressing further output)")

    await event_bus.subscribe(Channel.BAR, on_bar)

    config = DataConfig(csv_directory=str(output_dir), replay_speed=0.0)
    data_manager = DataManager(event_bus, config)

    # Register a provider for the whole directory
    csv_provider = CsvBarProvider(str(output_dir), replay_speed=0.0)
    data_manager.register_provider(csv_provider)

    await data_manager.start()

    # Give stream tasks time to complete (instant replay)
    await asyncio.sleep(1.0)
    await data_manager.stop()

    print(f"\nTotal bars processed: {bar_count}")
    print(f"Total events: {event_bus.total_published}")
    for ch, count in sorted(event_bus.channel_counts.items()):
        print(f"  {ch}: {count}")

    # ── Step 3: Show REST ingestion approach ───────────────────────────
    print("\n--- REST Ingestion Example ---")
    print("To send bars to a running platform instance:")
    print("")
    print("  import httpx")
    print("  async with httpx.AsyncClient() as client:")
    print('      resp = await client.post("http://localhost:8080/api/data/bars", json={')
    print('          "symbol": "AAPL",')
    print('          "open": 185.50, "high": 186.20,')
    print('          "low": 185.30, "close": 186.00,')
    print('          "volume": 125000,')
    print('          "timestamp": "2026-03-01T09:30:00Z"')
    print("      })")
    print('      print(resp.json())  # {"ingested": 1}')

    print(f"\nAll sample data saved to {output_dir.resolve()}/")


if __name__ == "__main__":
    asyncio.run(main())
