"""Example: Load CSV data into the platform via REST API.

Reads a CSV file and posts bars to the platform's REST ingestion
endpoint. Useful for loading historical data for backtesting or
replaying recorded market data.

Prerequisites:
    - pip install httpx
    - The trading platform must be running with ingestion enabled

Usage:
    python docs/examples/external_csv_feed.py sample_data/bars.csv
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

import httpx


async def load_csv_to_platform(
    csv_path: str,
    platform_url: str,
    batch_size: int = 100,
) -> None:
    """Read bars from CSV and POST them to the platform's ingestion endpoint."""

    path = Path(csv_path)
    if not path.exists():
        print(f"Error: file not found: {csv_path}")
        return

    # Read all bars from CSV
    bars: list[dict] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                "symbol": row["symbol"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "timestamp": row["timestamp"],
            })

    print(f"Loaded {len(bars)} bars from {csv_path}")

    # Post bars in batches
    ingested = 0
    async with httpx.AsyncClient() as client:
        for i in range(0, len(bars), batch_size):
            batch = bars[i : i + batch_size]
            resp = await client.post(
                f"{platform_url}/api/data/bars",
                json=batch,
            )

            if resp.status_code == 200:
                result = resp.json()
                ingested += result.get("ingested", 0)
                print(f"  Batch {i // batch_size + 1}: ingested {result.get('ingested', 0)} bars")
            else:
                print(f"  Batch {i // batch_size + 1}: error {resp.status_code} — {resp.text}")

    print(f"\nTotal ingested: {ingested} / {len(bars)} bars")

    # Check ingestion status
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{platform_url}/api/data/status")
        if resp.status_code == 200:
            print(f"Platform ingestion stats: {resp.json()}")


async def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "sample_data/bars.csv"
    platform_url = "http://localhost:8080"

    print(f"Loading {csv_path} into platform at {platform_url}")
    await load_csv_to_platform(csv_path, platform_url)


if __name__ == "__main__":
    asyncio.run(main())
