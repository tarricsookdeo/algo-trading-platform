"""Alpaca instrument provider.

Loads stock/option instruments from Alpaca's trading API and caches them.
"""

from __future__ import annotations

from typing import Any

import httpx

from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.core.enums import AssetClass
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Instrument


class AlpacaInstrumentProvider:
    """Loads and caches tradable instruments from Alpaca."""

    def __init__(self, config: AlpacaConfig) -> None:
        self._config = config
        self._log = get_logger("alpaca.instruments")
        self._instruments: dict[str, Instrument] = {}
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._config.trading_base_url,
            headers={
                "APCA-API-KEY-ID": self._config.api_key,
                "APCA-API-SECRET-KEY": self._config.api_secret,
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def load_stock_instruments(self) -> int:
        """Load all active stock instruments from Alpaca assets API."""
        assert self._client is not None
        try:
            resp = await self._client.get(
                "/v2/assets",
                params={"status": "active", "asset_class": "us_equity"},
            )
            resp.raise_for_status()
            assets: list[dict[str, Any]] = resp.json()
            count = 0
            for a in assets:
                symbol = a.get("symbol", "")
                if not symbol:
                    continue
                inst = Instrument(
                    symbol=symbol,
                    name=a.get("name", ""),
                    asset_class=AssetClass.STOCK,
                    exchange=a.get("exchange", ""),
                    tradable=a.get("tradable", False),
                    shortable=a.get("shortable", False),
                    marginable=a.get("marginable", False),
                    easy_to_borrow=a.get("easy_to_borrow", False),
                )
                self._instruments[symbol] = inst
                count += 1
            self._log.info("loaded stock instruments", count=count)
            return count
        except Exception as exc:
            self._log.error("failed to load stock instruments", error=str(exc))
            return 0

    def get_instrument(self, symbol: str) -> Instrument | None:
        return self._instruments.get(symbol)

    def get_all_instruments(self) -> dict[str, Instrument]:
        return dict(self._instruments)

    def search(self, query: str) -> list[Instrument]:
        """Search instruments by symbol or name prefix."""
        q = query.upper()
        return [
            inst
            for inst in self._instruments.values()
            if inst.symbol.startswith(q) or inst.name.upper().startswith(q)
        ]
