"""Alpaca data adapter facade.

Implements the DataAdapter interface and coordinates the stock stream,
options stream, REST client, and instrument provider.
"""

from __future__ import annotations

from trading_platform.adapters.alpaca.client import AlpacaClient
from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.adapters.alpaca.provider import AlpacaInstrumentProvider
from trading_platform.adapters.alpaca.stream import AlpacaOptionsStream, AlpacaStockStream
from trading_platform.adapters.base import DataAdapter
from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger


class AlpacaDataAdapter(DataAdapter):
    """Unified Alpaca data adapter.

    Owns the stock stream, options stream, REST client, and instrument
    provider. Publishes all data events onto the shared EventBus.
    """

    def __init__(self, config: AlpacaConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._log = get_logger("alpaca.adapter")

        self.stock_stream = AlpacaStockStream(config, event_bus)
        self.options_stream = AlpacaOptionsStream(config, event_bus)
        self.rest_client = AlpacaClient(config)
        self.instrument_provider = AlpacaInstrumentProvider(config)

        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Start all sub-components."""
        self._log.info("connecting Alpaca adapter")

        await self.rest_client.start()
        await self.instrument_provider.start()

        # Load instruments in background (non-blocking)
        try:
            count = await self.instrument_provider.load_stock_instruments()
            self._log.info("instruments loaded", count=count)
        except Exception as exc:
            self._log.warning("instrument load failed, continuing", error=str(exc))

        await self.stock_stream.start()
        self._connected = True

        await self._bus.publish(
            Channel.SYSTEM,
            {"component": "alpaca.adapter", "message": "connected", "level": "info"},
        )
        self._log.info("Alpaca adapter connected")

    async def disconnect(self) -> None:
        """Stop all sub-components."""
        self._log.info("disconnecting Alpaca adapter")
        await self.stock_stream.stop()
        await self.options_stream.stop()
        await self.rest_client.close()
        await self.instrument_provider.close()
        self._connected = False

        await self._bus.publish(
            Channel.SYSTEM,
            {"component": "alpaca.adapter", "message": "disconnected", "level": "info"},
        )

    async def subscribe_quotes(self, symbols: list[str]) -> None:
        await self.stock_stream.subscribe(quotes=symbols)

    async def subscribe_trades(self, symbols: list[str]) -> None:
        await self.stock_stream.subscribe(trades=symbols)

    async def subscribe_bars(self, symbols: list[str]) -> None:
        await self.stock_stream.subscribe(bars=symbols)

    async def unsubscribe(self, symbols: list[str]) -> None:
        await self.stock_stream.unsubscribe(symbols)
