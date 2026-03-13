"""Thin wrapper around AsyncPublicApiClient for options operations."""

from __future__ import annotations

from typing import Any

import httpx
from public_api_sdk import AsyncPublicApiClient, AsyncPublicApiClientConfiguration
from public_api_sdk.auth_config import ApiKeyAuthConfig
from public_api_sdk.models import (
    MultilegOrderRequest,
    OrderRequest,
    PreflightMultiLegRequest,
    PreflightRequest,
)

from trading_platform.adapters.options.config import OptionsConfig
from trading_platform.core.logging import get_logger

# Shared connection pool limits for options API
_POOL_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_TIMEOUT = httpx.Timeout(10.0)


class OptionsClient:
    """Wraps AsyncPublicApiClient options methods."""

    def __init__(self, config: OptionsConfig) -> None:
        self._config = config
        self._log = get_logger("options.client")
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
        self._log.info("options client connected", pool_max=20, keepalive=10)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
            self._log.info("options client disconnected")

    @property
    def raw(self) -> AsyncPublicApiClient:
        if not self._client:
            raise RuntimeError("Client not connected")
        return self._client

    async def place_option_order(
        self, request: OrderRequest, account_id: str | None = None
    ) -> Any:
        """Place a single-leg option order."""
        return await self.raw.place_order(request, account_id)

    async def place_multileg_order(
        self, request: MultilegOrderRequest, account_id: str | None = None
    ) -> Any:
        """Place a multi-leg option order."""
        return await self.raw.place_multileg_order(request, account_id)

    async def cancel_order(
        self, order_id: str, account_id: str | None = None
    ) -> None:
        """Cancel an option order."""
        await self.raw.cancel_order(order_id, account_id)

    async def get_option_portfolio(self, account_id: str | None = None) -> Any:
        """Get options portfolio positions."""
        return await self.raw.get_portfolio(account_id)

    async def perform_preflight(
        self, request: PreflightRequest, account_id: str | None = None
    ) -> Any:
        """Preflight check for a single-leg option order."""
        return await self.raw.perform_preflight_calculation(request, account_id)

    async def perform_multileg_preflight(
        self, request: PreflightMultiLegRequest, account_id: str | None = None
    ) -> Any:
        """Preflight check for a multi-leg option order."""
        return await self.raw.perform_multi_leg_preflight_calculation(request, account_id)

    async def get_option_chain(
        self, underlying: str, account_id: str | None = None
    ) -> Any:
        """Fetch option chain for an underlying symbol."""
        return await self.raw.get_option_chain(underlying, account_id)

    async def get_option_expirations(
        self, underlying: str, account_id: str | None = None
    ) -> Any:
        """Fetch available expirations for an underlying symbol."""
        return await self.raw.get_option_expirations(underlying, account_id)
