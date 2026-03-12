"""Backtest data collection example.

Uses the Alpaca REST client to fetch historical bars for one or more
symbols and saves them to CSV files for offline analysis and
backtesting.

Demonstrates:
- AlpacaClient initialization and lifecycle
- Fetching historical bars with date ranges
- Automatic pagination for large datasets
- Saving data to CSV with pandas (or manual CSV if pandas unavailable)

Prerequisites:
    - Set ALPACA_API_KEY and ALPACA_API_SECRET in your .env file
    - pip install -e .
    - Optional: pip install pandas (for DataFrame output)

Usage:
    python docs/examples/backtest_data_collection.py
"""

from __future__ import annotations

import asyncio
import csv
import os
from datetime import datetime, timezone
from pathlib import Path

from trading_platform.adapters.alpaca.client import AlpacaClient
from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.core.logging import get_logger, setup_logging


def save_bars_csv(bars: list[dict], filepath: Path) -> None:
    """Save bars to a CSV file."""
    if not bars:
        print(f"  No data for {filepath.name}")
        return

    fieldnames = ["t", "o", "h", "l", "c", "v", "vw", "n"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bars)

    print(f"  Saved {len(bars)} bars → {filepath}")


def save_bars_pandas(bars: list[dict], filepath: Path) -> None:
    """Save bars to CSV using pandas (if available)."""
    try:
        import pandas as pd
    except ImportError:
        save_bars_csv(bars, filepath)
        return

    if not bars:
        print(f"  No data for {filepath.name}")
        return

    df = pd.DataFrame(bars)
    # Rename Alpaca's short column names to readable ones
    column_map = {
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "vw": "vwap",
        "n": "trade_count",
    }
    df = df.rename(columns=column_map)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()

    df.to_csv(filepath)
    print(f"  Saved {len(df)} bars → {filepath}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")
    print(f"  Columns: {list(df.columns)}")


async def main() -> None:
    setup_logging(level="INFO")
    log = get_logger("example.backtest_data")

    # ── Configure ──────────────────────────────────────────────────────
    config = AlpacaConfig(
        api_key="YOUR_ALPACA_API_KEY",
        api_secret="YOUR_ALPACA_API_SECRET",
    )

    symbols = ["AAPL", "MSFT", "TSLA"]
    timeframe = "1Min"       # 1-minute bars
    start = "2026-03-01"     # Start date (ISO format)
    end = "2026-03-10"       # End date (ISO format)

    output_dir = Path("backtest_data")
    output_dir.mkdir(exist_ok=True)

    # ── Fetch data ─────────────────────────────────────────────────────
    client = AlpacaClient(config)
    await client.start()
    log.info("Alpaca REST client started")

    try:
        for symbol in symbols:
            print(f"\nFetching {timeframe} bars for {symbol} ({start} to {end})...")

            bars = await client.get_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                limit=10000,       # max per page (auto-paginates)
                feed="sip",        # SIP for full market data
                adjustment="raw",  # "raw", "split", "dividend", or "all"
            )

            filepath = output_dir / f"{symbol}_{timeframe}_{start}_{end}.csv"
            save_bars_pandas(bars, filepath)

        # ── Also fetch daily bars for longer-term analysis ─────────────
        print(f"\nFetching daily bars for the same symbols (past 1 year)...")
        for symbol in symbols:
            bars = await client.get_bars(
                symbol=symbol,
                timeframe="1Day",
                start="2025-03-01",
                end="2026-03-10",
                feed="sip",
                adjustment="split",  # adjust for stock splits
            )

            filepath = output_dir / f"{symbol}_1Day_1year.csv"
            save_bars_pandas(bars, filepath)

        # ── Fetch latest snapshot ──────────────────────────────────────
        print(f"\nFetching current snapshots...")
        for symbol in symbols:
            snapshot = await client.get_snapshot(symbol, feed="sip")
            latest = snapshot.get("latestTrade", {})
            print(f"  {symbol}: last trade @ ${latest.get('p', 'N/A')}")

    finally:
        await client.close()
        log.info("client closed")

    print(f"\nAll data saved to {output_dir.resolve()}/")


if __name__ == "__main__":
    asyncio.run(main())
