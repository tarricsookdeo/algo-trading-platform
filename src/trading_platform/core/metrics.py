"""Performance metrics collection and reporting.

Tracks ingestion throughput, processing rates, queue depth, and latency
so users can monitor and tune the platform.
"""

from __future__ import annotations

import time
from typing import Any


class PerformanceMetrics:
    """Collects and exposes platform performance counters.

    All rate calculations use a rolling window (default 5 seconds).
    """

    def __init__(self, window_seconds: float = 5.0) -> None:
        self._window = window_seconds

        # Counters
        self.messages_received: int = 0
        self.messages_processed: int = 0
        self.queue_drops: int = 0
        self.dashboard_broadcasts: int = 0

        # Rate tracking (list of (monotonic_time, count) tuples)
        self._received_ticks: list[tuple[float, int]] = []
        self._processed_ticks: list[tuple[float, int]] = []
        self._broadcast_ticks: list[tuple[float, int]] = []

        # Latency tracking
        self._latency_samples: list[float] = []
        self._max_samples = 1000

        # Queue depth (set externally)
        self.queue_depth: int = 0

    def record_received(self, count: int = 1) -> None:
        """Record that *count* messages were received (ingested)."""
        self.messages_received += count
        self._received_ticks.append((time.monotonic(), count))

    def record_processed(self, count: int = 1) -> None:
        """Record that *count* messages were processed (published to EventBus)."""
        self.messages_processed += count
        self._processed_ticks.append((time.monotonic(), count))

    def record_broadcast(self, count: int = 1) -> None:
        """Record a dashboard broadcast."""
        self.dashboard_broadcasts += count
        self._broadcast_ticks.append((time.monotonic(), count))

    def record_latency(self, latency_ms: float) -> None:
        """Record an enqueue-to-publish latency sample in milliseconds."""
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > self._max_samples:
            self._latency_samples = self._latency_samples[-self._max_samples:]

    def record_drop(self, count: int = 1) -> None:
        """Record dropped messages."""
        self.queue_drops += count

    # ── Rate helpers ─────────────────────────────────────────────────────

    def _rate(self, ticks: list[tuple[float, int]]) -> float:
        cutoff = time.monotonic() - self._window
        # Prune old entries in-place
        while ticks and ticks[0][0] < cutoff:
            ticks.pop(0)
        if not ticks:
            return 0.0
        total = sum(c for _, c in ticks)
        elapsed = time.monotonic() - ticks[0][0]
        return total / max(elapsed, 0.001)

    @property
    def ingestion_rate(self) -> float:
        """Messages received per second (rolling)."""
        return self._rate(self._received_ticks)

    @property
    def processing_rate(self) -> float:
        """Messages processed per second (rolling)."""
        return self._rate(self._processed_ticks)

    @property
    def broadcast_rate(self) -> float:
        """Dashboard broadcasts per second (rolling)."""
        return self._rate(self._broadcast_ticks)

    @property
    def avg_latency_ms(self) -> float:
        if not self._latency_samples:
            return 0.0
        return sum(self._latency_samples) / len(self._latency_samples)

    @property
    def max_latency_ms(self) -> float:
        if not self._latency_samples:
            return 0.0
        return max(self._latency_samples)

    # ── Snapshot ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable metrics snapshot."""
        return {
            "messages_received": self.messages_received,
            "messages_processed": self.messages_processed,
            "ingestion_rate": round(self.ingestion_rate, 1),
            "processing_rate": round(self.processing_rate, 1),
            "queue_depth": self.queue_depth,
            "queue_drops": self.queue_drops,
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "max_latency_ms": round(self.max_latency_ms, 3),
            "dashboard_broadcasts": self.dashboard_broadcasts,
            "dashboard_broadcast_rate": round(self.broadcast_rate, 1),
        }
