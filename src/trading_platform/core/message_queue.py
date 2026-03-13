"""Async message queue for decoupling data ingestion from processing.

Provides a bounded async queue with batched consumption, optional lossy mode
(drop oldest when full), and intra-batch quote deduplication.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine

from trading_platform.core.logging import get_logger

log = get_logger("core.message_queue")

BatchCallback = Callable[[list[dict[str, Any]]], Coroutine[Any, Any, None]]


class MessageQueue:
    """Async bounded message queue with batched consumption.

    Parameters
    ----------
    max_size : int
        Maximum number of messages in the queue.
    mode : str
        ``"lossy"`` drops the oldest message when full;
        ``"lossless"`` applies backpressure (blocks the producer).
    dedup_quotes : bool
        When True, only the latest quote per symbol is kept within a batch.
    """

    def __init__(
        self,
        max_size: int = 50_000,
        mode: str = "lossy",
        dedup_quotes: bool = True,
    ) -> None:
        self._max_size = max_size
        self._mode = mode
        self._dedup_quotes = dedup_quotes
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_size)
        self._consumer_task: asyncio.Task[None] | None = None
        self._running = False

        # Metrics
        self.enqueue_count: int = 0
        self.dequeue_count: int = 0
        self.drop_count: int = 0
        self._enqueue_times: dict[int, float] = {}  # id(msg) -> monotonic time
        self._latency_samples: list[float] = []
        self._max_latency_samples = 1000

    @property
    def depth(self) -> int:
        """Current number of messages in the queue."""
        return self._queue.qsize()

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def avg_latency_ms(self) -> float:
        """Average enqueue-to-dequeue latency in milliseconds."""
        if not self._latency_samples:
            return 0.0
        return sum(self._latency_samples) / len(self._latency_samples) * 1000

    @property
    def max_latency_ms(self) -> float:
        """Maximum observed enqueue-to-dequeue latency in milliseconds."""
        if not self._latency_samples:
            return 0.0
        return max(self._latency_samples) * 1000

    async def enqueue(self, event: dict[str, Any]) -> bool:
        """Put a message onto the queue.

        Returns True if the message was enqueued, False if it was dropped.
        """
        enqueue_time = time.monotonic()

        if self._queue.full():
            if self._mode == "lossy":
                # Drop the oldest message
                try:
                    old = self._queue.get_nowait()
                    old_id = id(old)
                    self._enqueue_times.pop(old_id, None)
                    self.drop_count += 1
                except asyncio.QueueEmpty:
                    pass
            else:
                # Lossless: block until space is available
                await self._queue.put(event)
                self.enqueue_count += 1
                self._enqueue_times[id(event)] = enqueue_time
                return True

        try:
            self._queue.put_nowait(event)
            self.enqueue_count += 1
            self._enqueue_times[id(event)] = enqueue_time
            return True
        except asyncio.QueueFull:
            self.drop_count += 1
            return False

    def start_consumer(
        self,
        callback: BatchCallback,
        batch_size: int = 100,
        flush_interval_ms: int = 10,
    ) -> None:
        """Start the async consumer task.

        The consumer dequeues up to *batch_size* messages at a time and calls
        *callback* with the batch.  A partial batch is flushed if
        *flush_interval_ms* elapses without filling the batch.
        """
        self._running = True
        self._consumer_task = asyncio.create_task(
            self._consume(callback, batch_size, flush_interval_ms)
        )

    async def stop(self) -> None:
        """Gracefully stop the consumer, draining remaining messages."""
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

    def get_metrics(self) -> dict[str, Any]:
        """Return a snapshot of queue metrics."""
        return {
            "enqueue_count": self.enqueue_count,
            "dequeue_count": self.dequeue_count,
            "depth": self.depth,
            "drop_count": self.drop_count,
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "max_latency_ms": round(self.max_latency_ms, 3),
            "mode": self._mode,
            "max_size": self._max_size,
        }

    # ── Internal ─────────────────────────────────────────────────────────

    async def _consume(
        self,
        callback: BatchCallback,
        batch_size: int,
        flush_interval_ms: int,
    ) -> None:
        """Consumer loop: dequeue batches and invoke the callback."""
        flush_interval = flush_interval_ms / 1000.0
        now = time.monotonic

        try:
            while self._running:
                batch: list[dict[str, Any]] = []
                deadline = now() + flush_interval

                # Collect up to batch_size items or until flush interval
                while len(batch) < batch_size:
                    remaining = deadline - now()
                    if remaining <= 0:
                        break
                    try:
                        msg = await asyncio.wait_for(
                            self._queue.get(), timeout=remaining
                        )
                        batch.append(msg)
                        self._record_latency(msg)
                    except asyncio.TimeoutError:
                        break

                if batch:
                    if self._dedup_quotes:
                        batch = self._dedup_quote_batch(batch)
                    self.dequeue_count += len(batch)
                    await callback(batch)
        except asyncio.CancelledError:
            # Drain remaining on shutdown
            while not self._queue.empty():
                try:
                    msg = self._queue.get_nowait()
                    self._record_latency(msg)
                    batch = [msg]
                    if self._dedup_quotes:
                        batch = self._dedup_quote_batch(batch)
                    self.dequeue_count += len(batch)
                    await callback(batch)
                except asyncio.QueueEmpty:
                    break

    def _record_latency(self, msg: dict[str, Any]) -> None:
        """Record the enqueue-to-dequeue latency for a message."""
        msg_id = id(msg)
        enqueue_time = self._enqueue_times.pop(msg_id, None)
        if enqueue_time is not None:
            latency = time.monotonic() - enqueue_time
            self._latency_samples.append(latency)
            if len(self._latency_samples) > self._max_latency_samples:
                self._latency_samples = self._latency_samples[-self._max_latency_samples:]

    @staticmethod
    def _dedup_quote_batch(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate quotes within a batch, keeping the latest per symbol.

        Non-quote events are passed through unchanged.  Quote events are
        identified by having ``type == "quote"`` in the event dict *or* by
        the event's channel being ``"quote"``.
        """
        result: list[dict[str, Any]] = []
        latest_quotes: dict[str, dict[str, Any]] = {}
        quote_positions: dict[str, int] = {}

        for i, msg in enumerate(batch):
            channel = msg.get("_channel", "")
            if channel == "quote":
                symbol = msg.get("data", {}).get("symbol", "") or msg.get("symbol", "")
                if symbol:
                    latest_quotes[symbol] = msg
                    quote_positions[symbol] = i
                else:
                    result.append(msg)
            else:
                result.append(msg)

        # Insert deduplicated quotes at their original positions (order-preserving)
        for symbol in sorted(quote_positions, key=lambda s: quote_positions[s]):
            result.append(latest_quotes[symbol])

        return result
