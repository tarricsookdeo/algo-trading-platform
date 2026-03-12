"""Abstract base class for data providers.

Users implement DataProvider to bring any data source into the platform.
The platform calls connect/disconnect and iterates over the async streams.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from trading_platform.core.models import Bar, QuoteTick, TradeTick


class DataProvider(ABC):
    """Abstract base for data sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the data source (open connections, authenticate, etc.)."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up resources."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    async def get_historical_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "1min"
    ) -> list[Bar]:
        """Fetch historical OHLCV bars. Override if provider supports historical data."""
        return []

    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        """Yield bars as they complete. Override for live bar streaming."""
        return
        yield  # make it an async generator

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[QuoteTick]:
        """Yield real-time quotes. Override for live quote streaming."""
        return
        yield

    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[TradeTick]:
        """Yield real-time trades. Override for live trade streaming."""
        return
        yield
