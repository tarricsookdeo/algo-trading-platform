"""DataManager — orchestrates all data ingestion into the platform.

Registers and manages DataProvider instances, runs their streaming tasks,
and publishes all data to the EventBus as normalized events.  Optionally
routes messages through a MessageQueue for decoupled, batched processing.
"""

from __future__ import annotations

import asyncio
from typing import Any

from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.message_queue import MessageQueue
from trading_platform.core.metrics import PerformanceMetrics
from trading_platform.data.config import DataConfig
from trading_platform.data.provider import DataProvider

log = get_logger("data.manager")


class DataManager:
    """Orchestrates all data ingestion into the platform."""

    def __init__(
        self,
        event_bus: EventBus,
        config: DataConfig | None = None,
        message_queue: MessageQueue | None = None,
        perf_metrics: PerformanceMetrics | None = None,
    ) -> None:
        self._bus = event_bus
        self._config = config or DataConfig()
        self._providers: dict[str, DataProvider] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._mq = message_queue
        self._perf = perf_metrics

        # Ingestion stats
        self.bars_received: int = 0
        self.quotes_received: int = 0
        self.trades_received: int = 0

    def register_provider(self, provider: DataProvider) -> None:
        """Register a data provider."""
        self._providers[provider.name] = provider
        log.info("provider registered", provider=provider.name)

    async def start(self) -> None:
        """Connect all providers and start stream tasks."""
        self._running = True
        for name, provider in self._providers.items():
            try:
                await provider.connect()
                log.info("provider connected", provider=name)
            except Exception:
                log.exception("provider connect failed", provider=name)
                continue

            # Start streaming tasks for each provider
            self._tasks.append(asyncio.create_task(self._run_bar_stream(provider)))
            self._tasks.append(asyncio.create_task(self._run_quote_stream(provider)))
            self._tasks.append(asyncio.create_task(self._run_trade_stream(provider)))

    async def stop(self) -> None:
        """Disconnect all providers and cancel tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        for name, provider in self._providers.items():
            try:
                await provider.disconnect()
            except Exception:
                log.exception("provider disconnect failed", provider=name)

    def get_provider_status(self) -> list[dict[str, Any]]:
        """Return status of all registered providers."""
        return [
            {
                "name": name,
                "connected": provider.is_connected,
            }
            for name, provider in self._providers.items()
        ]

    def get_ingestion_stats(self) -> dict[str, Any]:
        """Return ingestion statistics."""
        return {
            "bars_received": self.bars_received,
            "quotes_received": self.quotes_received,
            "trades_received": self.trades_received,
            "providers": len(self._providers),
        }

    async def publish_bar(self, bar_data: dict[str, Any]) -> None:
        """Publish a bar event from ingestion."""
        self.bars_received += 1
        if self._perf:
            self._perf.record_received()
        if self._mq:
            bar_data["_channel"] = str(Channel.BAR)
            await self._mq.enqueue(bar_data)
        else:
            await self._bus.publish(Channel.BAR, bar_data)

    async def publish_quote(self, quote_data: dict[str, Any]) -> None:
        """Publish a quote event from ingestion."""
        self.quotes_received += 1
        if self._perf:
            self._perf.record_received()
        if self._mq:
            quote_data["_channel"] = str(Channel.QUOTE)
            await self._mq.enqueue(quote_data)
        else:
            await self._bus.publish(Channel.QUOTE, quote_data)

    async def publish_trade(self, trade_data: dict[str, Any]) -> None:
        """Publish a trade event from ingestion."""
        self.trades_received += 1
        if self._perf:
            self._perf.record_received()
        if self._mq:
            trade_data["_channel"] = str(Channel.TRADE)
            await self._mq.enqueue(trade_data)
        else:
            await self._bus.publish(Channel.TRADE, trade_data)

    async def _run_bar_stream(self, provider: DataProvider) -> None:
        """Run bar streaming for a provider."""
        try:
            async for bar in provider.stream_bars([]):
                if not self._running:
                    break
                self.bars_received += 1
                data = bar.model_dump(mode="json")
                if self._perf:
                    self._perf.record_received()
                if self._mq:
                    data["_channel"] = str(Channel.BAR)
                    await self._mq.enqueue(data)
                else:
                    await self._bus.publish(Channel.BAR, data)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("bar stream error", provider=provider.name)

    async def _run_quote_stream(self, provider: DataProvider) -> None:
        """Run quote streaming for a provider."""
        try:
            async for quote in provider.stream_quotes([]):
                if not self._running:
                    break
                self.quotes_received += 1
                data = quote.model_dump(mode="json")
                if self._perf:
                    self._perf.record_received()
                if self._mq:
                    data["_channel"] = str(Channel.QUOTE)
                    await self._mq.enqueue(data)
                else:
                    await self._bus.publish(Channel.QUOTE, data)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("quote stream error", provider=provider.name)

    async def _run_trade_stream(self, provider: DataProvider) -> None:
        """Run trade streaming for a provider."""
        try:
            async for trade in provider.stream_trades([]):
                if not self._running:
                    break
                self.trades_received += 1
                data = trade.model_dump(mode="json")
                if self._perf:
                    self._perf.record_received()
                if self._mq:
                    data["_channel"] = str(Channel.TRADE)
                    await self._mq.enqueue(data)
                else:
                    await self._bus.publish(Channel.TRADE, data)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("trade stream error", provider=provider.name)
