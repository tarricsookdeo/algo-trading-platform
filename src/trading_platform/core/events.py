"""Async event bus with pub/sub pattern.

All platform components communicate through this bus. Channels are defined
in enums.Channel. Subscribing to "*" receives all events.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

from trading_platform.core.enums import Channel

Callback = Callable[[str, Any], Coroutine[Any, Any, None]]


class EventBus:
    """Async publish/subscribe event bus.

    Supports named channels and wildcard subscriptions. Tracks basic
    throughput metrics.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = defaultdict(list)
        self._lock = asyncio.Lock()

        # Metrics
        self.total_published: int = 0
        self.channel_counts: dict[str, int] = defaultdict(int)
        self._second_counts: list[tuple[float, int]] = []

    async def publish(self, channel: str | Channel, event: Any) -> None:
        """Publish an event to a channel.

        All subscribers on the channel and wildcard subscribers are called
        concurrently via asyncio.gather.
        """
        ch = str(channel)
        self.total_published += 1
        self.channel_counts[ch] += 1
        self._second_counts.append((time.monotonic(), 1))

        callbacks: list[Callback] = []
        async with self._lock:
            callbacks.extend(self._subscribers.get(ch, []))
            if ch != "*":
                callbacks.extend(self._subscribers.get("*", []))

        if callbacks:
            await asyncio.gather(
                *(cb(ch, event) for cb in callbacks),
                return_exceptions=True,
            )

    async def subscribe(self, channel: str | Channel, callback: Callback) -> None:
        """Subscribe a callback to a channel. Use '*' for all events."""
        ch = str(channel)
        async with self._lock:
            if callback not in self._subscribers[ch]:
                self._subscribers[ch].append(callback)

    async def unsubscribe(self, channel: str | Channel, callback: Callback) -> None:
        """Remove a callback from a channel."""
        ch = str(channel)
        async with self._lock:
            try:
                self._subscribers[ch].remove(callback)
            except ValueError:
                pass

    def events_per_second(self) -> float:
        """Return the rolling events-per-second rate over the last 5 seconds."""
        cutoff = time.monotonic() - 5.0
        self._second_counts = [
            (t, c) for t, c in self._second_counts if t > cutoff
        ]
        if not self._second_counts:
            return 0.0
        total = sum(c for _, c in self._second_counts)
        elapsed = time.monotonic() - self._second_counts[0][0]
        return total / max(elapsed, 0.001)

    @property
    def subscriber_count(self) -> int:
        """Total number of active subscriptions."""
        return sum(len(subs) for subs in self._subscribers.values())
