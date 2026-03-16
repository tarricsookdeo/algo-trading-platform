"""Thin wrapper around AsyncPublicApiClient for crypto operations."""

from __future__ import annotations

from typing import Any

import httpx
from public_api_sdk import AsyncPublicApiClient, AsyncPublicApiClientConfiguration
from public_api_sdk.auth_config import ApiKeyAuthConfig

from trading_platform.adapters.crypto.config import CryptoConfig
from trading_platform.core.logging import get_logger

# Shared connection pool limits for crypto API
_POOL_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_TIMEOUT = httpx.Timeout(10.0)


class CryptoClient:
    """Wraps AsyncPublicApiClient crypto methods."""

    def __init__(self, config: CryptoConfig) -> None:
        self._config = config
        self._log = get_logger("crypto.client")
        self._client: AsyncPublicApiClient | None = None

    async def connect(self) -> None:
        auth_config = ApiKeyAuthConfig(
            api_secret_key=self._config.api_secret,
            validity_minutes=self._config.token_validity_minutes,
        )
        config = AsyncPublicApiClientConfiguration(
            default_account_number=self._config.account_id,
        )
        self._client = AsyncPublicApiClient(auth_config=auth_config, config=config)
        # Replace the SDK's default httpx client with a pool-configured one
        old_client = self._client.api_client._client
        self._client.api_client._client = httpx.AsyncClient(
            headers=dict(old_client.headers),
            limits=_POOL_LIMITS,
            timeout=_TIMEOUT,
        )
        await self._client.__aenter__()
        self._log.info("crypto client connected", pool_max=20, keepalive=10)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
            self._log.info("crypto client disconnected")

    @property
    def raw(self) -> AsyncPublicApiClient:
        if not self._client:
            raise RuntimeError("Client not connected")
        return self._client

    async def place_crypto_order(self, **kwargs: Any) -> Any:
        """Place a crypto order via the SDK."""
        return await self.raw.place_crypto_order(**kwargs)

    async def cancel_crypto_order(self, order_id: str) -> None:
        """Cancel a crypto order."""
        await self.raw.cancel_crypto_order(order_id)

    async def get_portfolio(self) -> Any:
        """Get portfolio — crypto positions are filtered from the full response."""
        return await self.raw.get_portfolio()
