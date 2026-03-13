"""Async event bus with pub/sub pattern.

All platform components communicate through this bus. Channels are defined
in enums.Channel. Subscribing to "*" receives all events.

Supports optional **topic-based routing**: subscribers can filter on a topic
(e.g. a symbol) so they only receive events whose ``topic`` matches.
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

    Supports named channels, wildcard subscriptions, and optional topic-based
    filtering.  Tracks basic throughput metrics.

    Topic routing
    -------------
    ``subscribe("quote", handler, topic="AAPL")`` registers *handler* to
    receive only quote events published with ``topic="AAPL"``.  A subscriber
    with ``topic=None`` (the default) receives **all** events on that channel,
    regardless of the topic they were published with.
    """

    def __init__(self) -> None:
        # channel → topic (None = broad) → list of callbacks
        self._subscribers: dict[str, dict[str | None, list[Callback]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._lock = asyncio.Lock()

        # Metrics
        self.total_published: int = 0
        self.channel_counts: dict[str, int] = defaultdict(int)
        self._second_counts: list[tuple[float, int]] = []
        self.topic_filtered_count: int = 0  # events dispatched via topic routing

    async def publish(
        self,
        channel: str | Channel,
        event: Any,
        *,
        topic: str | None = None,
    ) -> None:
        """Publish an event to a channel, optionally with a topic.

        Dispatches to:
        1. Topic-specific subscribers (if *topic* is given).
        2. Broad subscribers (subscribed with ``topic=None``).
        3. Wildcard (``"*"``) subscribers.
        """
        ch = str(channel)
        self.total_published += 1
        self.channel_counts[ch] += 1
        self._second_counts.append((time.monotonic(), 1))

        callbacks: list[Callback] = []
        async with self._lock:
            ch_map = self._subscribers.get(ch)
            if ch_map:
                # Broad (topic=None) subscribers always receive events
                callbacks.extend(ch_map.get(None, []))
                # Topic-specific subscribers receive only matching events
                if topic is not None:
                    topic_cbs = ch_map.get(topic, [])
                    if topic_cbs:
                        callbacks.extend(topic_cbs)
                        self.topic_filtered_count += len(topic_cbs)
            if ch != "*":
                wildcard_map = self._subscribers.get("*")
                if wildcard_map:
                    callbacks.extend(wildcard_map.get(None, []))

        if callbacks:
            await asyncio.gather(
                *(cb(ch, event) for cb in callbacks),
                return_exceptions=True,
            )

    async def subscribe(
        self,
        channel: str | Channel,
        callback: Callback,
        *,
        topic: str | None = None,
    ) -> None:
        """Subscribe a callback to a channel.

        Use ``topic`` to receive only events published with that topic.
        Use ``'*'`` as channel for all events.
        """
        ch = str(channel)
        async with self._lock:
            subs = self._subscribers[ch][topic]
            if callback not in subs:
                subs.append(callback)

    async def unsubscribe(
        self,
        channel: str | Channel,
        callback: Callback,
        *,
        topic: str | None = None,
    ) -> None:
        """Remove a callback from a channel (and optional topic)."""
        ch = str(channel)
        async with self._lock:
            ch_map = self._subscribers.get(ch)
            if ch_map:
                subs = ch_map.get(topic)
                if subs:
                    try:
                        subs.remove(callback)
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
        return sum(
            len(cbs)
            for topic_map in self._subscribers.values()
            for cbs in topic_map.values()
        )
