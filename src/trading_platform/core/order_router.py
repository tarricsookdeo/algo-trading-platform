"""Order router that dispatches orders to the correct execution adapter by asset class."""

from __future__ import annotations

from typing import Any

from trading_platform.adapters.base import ExecAdapter
from trading_platform.core.enums import AssetClass
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Order


class OrderRouter(ExecAdapter):
    """Routes orders to asset-class-specific execution adapters.

    Implements ExecAdapter so it can be used as a drop-in replacement
    wherever a single adapter is expected.
    """

    def __init__(self) -> None:
        self._adapters: dict[AssetClass, ExecAdapter] = {}
        self._log = get_logger("order_router")

    def register(self, asset_class: AssetClass, adapter: ExecAdapter) -> None:
        """Register an execution adapter for an asset class."""
        self._adapters[asset_class] = adapter
        self._log.info("adapter registered", asset_class=str(asset_class))

    def get_adapter(self, asset_class: AssetClass) -> ExecAdapter | None:
        """Return the adapter for a given asset class."""
        return self._adapters.get(asset_class)

    async def connect(self) -> None:
        """Connect all registered adapters."""
        for ac, adapter in self._adapters.items():
            self._log.info("connecting adapter", asset_class=str(ac))
            await adapter.connect()

    async def disconnect(self) -> None:
        """Disconnect all registered adapters."""
        for ac, adapter in self._adapters.items():
            self._log.info("disconnecting adapter", asset_class=str(ac))
            await adapter.disconnect()

    async def submit_order(self, order: Order) -> Any:
        """Route an order to the appropriate adapter based on its asset_class."""
        adapter = self._adapters.get(order.asset_class)
        if not adapter:
            raise ValueError(f"No adapter registered for asset class {order.asset_class!r}")
        return await adapter.submit_order(order)

    async def cancel_order(self, order_id: str) -> Any:
        """Cancel an order — tries all adapters since we don't track which one owns it."""
        for adapter in self._adapters.values():
            try:
                return await adapter.cancel_order(order_id)
            except Exception:
                continue
        raise ValueError(f"No adapter could cancel order {order_id}")

    async def get_positions(self) -> list[Any]:
        """Aggregate positions from all adapters."""
        all_positions: list[Any] = []
        for adapter in self._adapters.values():
            positions = await adapter.get_positions()
            all_positions.extend(positions)
        return all_positions

    async def get_account(self) -> Any:
        """Aggregate account info from all adapters."""
        accounts: dict[str, Any] = {}
        for ac, adapter in self._adapters.items():
            accounts[str(ac)] = await adapter.get_account()
        return accounts
