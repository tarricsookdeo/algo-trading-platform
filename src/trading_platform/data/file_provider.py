"""File-based data provider for CSV historical data."""

from __future__ import annotations

import asyncio
import csv
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from trading_platform.core.models import Bar
from trading_platform.data.provider import DataProvider


class CsvBarProvider(DataProvider):
    """Load historical bars from CSV files.

    Expected CSV format:
        timestamp,symbol,open,high,low,close,volume
        2024-01-15T09:30:00,AAPL,185.50,186.20,185.30,186.00,125000
    """

    def __init__(self, file_path: str, replay_speed: float = 0.0) -> None:
        self._file_path = file_path
        self._replay_speed = replay_speed
        self._connected = False
        self._bars: list[Bar] = []

    @property
    def name(self) -> str:
        return f"csv:{self._file_path}"

    async def connect(self) -> None:
        self._bars = self._load_bars()
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._bars.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_historical_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "1min"
    ) -> list[Bar]:
        return [
            b for b in self._bars
            if b.symbol == symbol and start <= b.timestamp <= end
        ]

    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        prev_ts: datetime | None = None
        for bar in self._bars:
            if self._replay_speed > 0 and prev_ts is not None:
                delta = (bar.timestamp - prev_ts).total_seconds()
                await asyncio.sleep(delta / self._replay_speed)
            prev_ts = bar.timestamp
            yield bar

    def _load_bars(self) -> list[Bar]:
        """Read bars from CSV file(s)."""
        path = Path(self._file_path)
        bars: list[Bar] = []
        files = list(path.glob("*.csv")) if path.is_dir() else [path]
        for f in files:
            bars.extend(self._read_csv(f))
        bars.sort(key=lambda b: b.timestamp)
        return bars

    @staticmethod
    def _read_csv(file_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(file_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bars.append(Bar(
                    symbol=row["symbol"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                ))
        return bars

