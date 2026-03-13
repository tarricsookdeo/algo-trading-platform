"""WebSocket connection manager for the dashboard.

Bridges the platform EventBus to browser clients, broadcasting market data
and system metrics over WebSocket.  When a DashboardThrottler is provided,
high-frequency market data events are buffered and flushed at a fixed
interval instead of being broadcast immediately.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from fastapi import WebSocket

from trading_platform.core import clock
from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.metrics import PerformanceMetrics
from trading_platform.dashboard.throttler import DashboardThrottler


class DashboardWSManager:
    """Manages WebSocket connections from dashboard clients.

    Subscribes to all EventBus channels and forwards events as JSON to
    connected browsers. Sends periodic system metrics.
    """

    # Channels that go through the throttler when enabled
    _THROTTLED_CHANNELS = {"quote", "trade", "bar"}

    def __init__(
        self,
        event_bus: EventBus,
        throttler: DashboardThrottler | None = None,
        perf_metrics: PerformanceMetrics | None = None,
    ) -> None:
        self._bus = event_bus
        self._log = get_logger("dashboard.ws")
        self._clients: list[WebSocket] = []
        self._start_time = time.monotonic()
        self._metrics_task: asyncio.Task[None] | None = None
        self._throttler = throttler
        self._perf = perf_metrics

    async def start(self) -> None:
        """Subscribe to all event bus channels."""
        await self._bus.subscribe("*", self._on_event)
        self._metrics_task = asyncio.create_task(self._metrics_loop())
        if self._throttler:
            self._throttler.start(self.broadcast)
        self._log.info("dashboard WS manager started")

    async def stop(self) -> None:
        await self._bus.unsubscribe("*", self._on_event)
        if self._throttler:
            await self._throttler.stop()
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        self._log.info("dashboard client connected", total=len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        if ws in self._clients:
            self._clients.remove(ws)
        self._log.info("dashboard client disconnected", total=len(self._clients))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a JSON message to all connected clients."""
        if not self._clients:
            return
        if self._perf:
            self._perf.record_broadcast()
        text = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._clients:
                self._clients.remove(ws)

    # ── Internal ──────────────────────────────────────────────────────

    async def _on_event(self, channel: str, event: Any) -> None:
        """Forward event bus events to dashboard clients."""
        # Route high-frequency data through throttler if available
        if self._throttler and channel in self._THROTTLED_CHANNELS:
            await self._throttler.buffer_event(channel, event)
            return

        payload: dict[str, Any]
        if hasattr(event, "model_dump"):
            payload = {"type": channel, "data": event.model_dump(mode="json")}
        elif isinstance(event, dict):
            payload = {"type": channel, "data": event}
        else:
            payload = {"type": channel, "data": str(event)}

        # Annotate with category for client-side routing
        category = self._categorize_event(channel)
        if category:
            payload["category"] = category

        await self.broadcast(payload)

    @staticmethod
    def _categorize_event(channel: str) -> str | None:
        """Map event channels to UI categories for client-side routing."""
        if channel.startswith("trailing_stop."):
            return "trailing_stop"
        if channel.startswith("scaled."):
            return "scaled_order"
        if channel.startswith("bracket."):
            return "bracket"
        if channel.startswith("options.expiration.") or channel.startswith("options.position."):
            return "expiration"
        if channel in ("quote", "trade", "bar"):
            return "market_data"
        if channel.startswith("execution."):
            return "execution"
        if channel.startswith("risk."):
            return "risk"
        if channel.startswith("strategy."):
            return "strategy"
        return None

    async def _metrics_loop(self) -> None:
        """Send system metrics every 2 seconds."""
        while True:
            try:
                await asyncio.sleep(2.0)
                uptime = time.monotonic() - self._start_time
                try:
                    process = os.getpid()
                    with open(f"/proc/{process}/status") as f:
                        mem_line = [l for l in f if l.startswith("VmRSS")]
                    mem_kb = int(mem_line[0].split()[1]) if mem_line else 0
                    mem_mb = mem_kb / 1024
                except Exception:
                    mem_mb = 0.0

                metrics = {
                    "type": "metrics",
                    "data": {
                        "uptime_seconds": round(uptime, 1),
                        "messages_per_second": round(self._bus.events_per_second(), 1),
                        "total_messages": self._bus.total_published,
                        "active_subscribers": self._bus.subscriber_count,
                        "memory_mb": round(mem_mb, 1),
                        "connected_clients": len(self._clients),
                        "timestamp": clock.now().isoformat(),
                    },
                }
                await self.broadcast(metrics)
            except asyncio.CancelledError:
                break
            except Exception:
                pass
