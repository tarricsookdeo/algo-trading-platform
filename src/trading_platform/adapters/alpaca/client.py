"""Alpaca REST HTTP client for historical data.

Uses httpx.AsyncClient with built-in rate limiting, pagination,
and retry logic with exponential backoff.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.core.logging import get_logger


class AlpacaClient:
    """Async HTTP client for Alpaca's data REST API.

    Features:
    - Automatic rate limiting (10,000 requests/minute)
    - Pagination via next_page_token
    - Retry with exponential backoff on 429 and 5xx
    """

    RATE_LIMIT = 10_000  # requests per minute
    MAX_RETRIES = 5

    def __init__(self, config: AlpacaConfig) -> None:
        self._config = config
        self._log = get_logger("alpaca.client")
        self._client: httpx.AsyncClient | None = None

        # Simple token-bucket rate limiter
        self._request_times: list[float] = []

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._config.rest_base_url,
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

    # ── Public Methods ────────────────────────────────────────────────

    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Min",
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        limit: int = 1000,
        feed: str | None = None,
        adjustment: str = "raw",
    ) -> list[dict[str, Any]]:
        """Fetch historical bars with automatic pagination."""
        params: dict[str, Any] = {
            "timeframe": timeframe,
            "limit": min(limit, 10000),
            "adjustment": adjustment,
        }
        if start:
            params["start"] = _fmt_dt(start)
        if end:
            params["end"] = _fmt_dt(end)
        if feed:
            params["feed"] = feed

        return await self._paginate(f"/v2/stocks/{symbol}/bars", "bars", params)

    async def get_trades(
        self,
        symbol: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        limit: int = 1000,
        feed: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": min(limit, 10000)}
        if start:
            params["start"] = _fmt_dt(start)
        if end:
            params["end"] = _fmt_dt(end)
        if feed:
            params["feed"] = feed

        return await self._paginate(f"/v2/stocks/{symbol}/trades", "trades", params)

    async def get_quotes(
        self,
        symbol: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        limit: int = 1000,
        feed: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": min(limit, 10000)}
        if start:
            params["start"] = _fmt_dt(start)
        if end:
            params["end"] = _fmt_dt(end)
        if feed:
            params["feed"] = feed

        return await self._paginate(f"/v2/stocks/{symbol}/quotes", "quotes", params)

    async def get_snapshot(self, symbol: str, feed: str | None = None) -> dict[str, Any]:
        params = {}
        if feed:
            params["feed"] = feed
        return await self._request("GET", f"/v2/stocks/{symbol}/snapshot", params=params)

    async def get_latest_trade(self, symbol: str, feed: str | None = None) -> dict[str, Any]:
        params = {}
        if feed:
            params["feed"] = feed
        return await self._request("GET", f"/v2/stocks/{symbol}/trades/latest", params=params)

    async def get_latest_quote(self, symbol: str, feed: str | None = None) -> dict[str, Any]:
        params = {}
        if feed:
            params["feed"] = feed
        return await self._request("GET", f"/v2/stocks/{symbol}/quotes/latest", params=params)

    # ── Internal ──────────────────────────────────────────────────────

    async def _paginate(
        self, path: str, key: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated endpoint."""
        results: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            if page_token:
                params["page_token"] = page_token
            data = await self._request("GET", path, params=params)
            results.extend(data.get(key, []))
            page_token = data.get("next_page_token")
            if not page_token:
                break

        return results

    async def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a rate-limited, retried request."""
        assert self._client is not None, "Client not started. Call start() first."

        await self._rate_limit()

        backoff = 1.0
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self._client.request(method, path, params=params)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("retry-after", backoff))
                    self._log.warning("rate limited, backing off", retry_after=retry_after)
                    await asyncio.sleep(retry_after)
                    backoff = min(backoff * 2, 60.0)
                    continue
                if resp.status_code >= 500:
                    self._log.warning(
                        "server error, retrying",
                        status=resp.status_code,
                        attempt=attempt,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                self._log.warning("request timeout, retrying", attempt=attempt)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

        raise RuntimeError(f"Request failed after {self.MAX_RETRIES} retries: {method} {path}")

    async def _rate_limit(self) -> None:
        """Simple sliding-window rate limiter."""
        now = time.monotonic()
        cutoff = now - 60.0
        self._request_times = [t for t in self._request_times if t > cutoff]
        if len(self._request_times) >= self.RATE_LIMIT:
            sleep_for = self._request_times[0] - cutoff
            self._log.debug("rate limit throttle", sleep_for=sleep_for)
            await asyncio.sleep(sleep_for)
        self._request_times.append(time.monotonic())


def _fmt_dt(dt: str | datetime) -> str:
    """Format a datetime to RFC-3339 string."""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return dt
