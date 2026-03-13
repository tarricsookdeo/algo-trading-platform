"""Dashboard update throttler.

Buffers incoming events and flushes them to WebSocket clients at a fixed
interval, deduplicating quotes by symbol and capping trade events per flush.
This reduces WebSocket broadcast overhead from potentially thousands/second
down to ~10/second.
"""

from __future__ import annotations

import asyncio
from typing import Any

from trading_platform.core.logging import get_logger

log = get_logger("dashboard.throttler")


class DashboardThrottler:
    """Buffer and throttle dashboard WebSocket updates.

    Parameters
    ----------
    flush_interval_ms : int
        How often to push buffered updates (default 100ms = 10 flushes/sec).
    max_trades_per_flush : int
        Maximum trade events sent per flush (default 50).
    """

    def __init__(
        self,
        flush_interval_ms: int = 100,
        max_trades_per_flush: int = 50,
    ) -> None:
        self._flush_interval = flush_interval_ms / 1000.0
        self._max_trades = max_trades_per_flush

        # Buffers
        self._quotes: dict[str, dict[str, Any]] = {}  # symbol -> latest quote
        self._trades: list[dict[str, Any]] = []
        self._bars: dict[str, dict[str, Any]] = {}  # symbol -> latest bar
        self._other: list[dict[str, Any]] = []

        # Callback and task
        self._broadcast_fn: Any = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()

        # Metrics
        self.flush_count: int = 0
        self.events_buffered: int = 0
        self.events_flushed: int = 0

    def start(self, broadcast_fn: Any) -> None:
        """Start the throttler flush loop.

        *broadcast_fn* should be an async callable that sends a dict to all
        connected WebSocket clients.
        """
        self._broadcast_fn = broadcast_fn
        self._running = True
        self._task = asyncio.create_task(self._flush_loop())
        log.info("dashboard throttler started", interval_ms=int(self._flush_interval * 1000))

    async def stop(self) -> None:
        """Stop the flush loop and flush any remaining buffered events."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Final flush
        await self._flush()

    async def buffer_event(self, channel: str, event: Any) -> None:
        """Buffer an event for the next flush.

        Events are categorised by channel to enable per-type deduplication.
        """
        self.events_buffered += 1
        payload: dict[str, Any]
        if hasattr(event, "model_dump"):
            payload = {"type": channel, "data": event.model_dump(mode="json")}
        elif isinstance(event, dict):
            payload = {"type": channel, "data": event}
        else:
            payload = {"type": channel, "data": str(event)}

        async with self._lock:
            if channel == "quote":
                symbol = event.get("symbol", "") if isinstance(event, dict) else ""
                if symbol:
                    self._quotes[symbol] = payload
                else:
                    self._other.append(payload)
            elif channel == "trade":
                self._trades.append(payload)
            elif channel == "bar":
                symbol = event.get("symbol", "") if isinstance(event, dict) else ""
                if symbol:
                    self._bars[symbol] = payload
                else:
                    self._other.append(payload)
            else:
                self._other.append(payload)

    async def _flush_loop(self) -> None:
        """Periodically flush buffered events."""
        try:
            while self._running:
                await asyncio.sleep(self._flush_interval)
                await self._flush()
        except asyncio.CancelledError:
            pass

    async def _flush(self) -> None:
        """Flush all buffered events as a single batched message."""
        async with self._lock:
            updates: list[dict[str, Any]] = []

            # Quotes (deduplicated — one per symbol)
            for payload in self._quotes.values():
                updates.append(payload)
            self._quotes.clear()

            # Bars (deduplicated — one per symbol)
            for payload in self._bars.values():
                updates.append(payload)
            self._bars.clear()

            # Trades (capped)
            trades_to_send = self._trades[-self._max_trades:]
            updates.extend(trades_to_send)
            self._trades.clear()

            # Other events
            updates.extend(self._other)
            self._other.clear()

        if not updates and not self._broadcast_fn:
            return

        if updates and self._broadcast_fn:
            self.flush_count += 1
            self.events_flushed += len(updates)
            await self._broadcast_fn({
                "type": "batch",
                "updates": updates,
                "count": len(updates),
            })
