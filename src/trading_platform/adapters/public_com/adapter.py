"""Public.com execution adapter implementing ExecAdapter."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

from public_api_sdk.models import (
    CancelAndReplaceRequest,
    InstrumentType,
    LegInstrument,
    LegInstrumentType,
    MultilegOrderRequest,
    OpenCloseIndicator,
    OrderExpirationRequest,
    OrderInstrument,
    OrderLegRequest,
    OrderRequest,
    OrderSide as SDKOrderSide,
    OrderStatus as SDKOrderStatus,
    OrderType as SDKOrderType,
    PreflightRequest,
    TimeInForce,
)
from public_api_sdk.exceptions import APIError, RateLimitError

from trading_platform.adapters.base import ExecAdapter
from trading_platform.adapters.public_com.client import PublicComClient
from trading_platform.adapters.public_com.config import PublicComConfig
from trading_platform.adapters.public_com.parse import (
    map_order_status,
    sdk_order_to_platform,
    sdk_position_to_platform,
)
from trading_platform.core.enums import AssetClass, OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Order, Position

# Terminal SDK statuses
_TERMINAL_STATUSES = {"FILLED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED", "REPLACED"}

# Map platform enums to SDK enums
_SIDE_TO_SDK = {
    OrderSide.BUY: SDKOrderSide.BUY,
    OrderSide.SELL: SDKOrderSide.SELL,
}

_TYPE_TO_SDK = {
    OrderType.MARKET: SDKOrderType.MARKET,
    OrderType.LIMIT: SDKOrderType.LIMIT,
    OrderType.STOP: SDKOrderType.STOP,
    OrderType.STOP_LIMIT: SDKOrderType.STOP_LIMIT,
}


class PublicComExecAdapter(ExecAdapter):
    """Execution adapter for Public.com using the publicdotcom-py SDK."""

    def __init__(self, config: PublicComConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._log = get_logger("public_com.adapter")
        self._client = PublicComClient(config)
        self._connected = False
        self._portfolio_task: asyncio.Task[None] | None = None
        self._tracked_orders: dict[str, Any] = {}
        self._positions: list[Position] = []
        self._account_info: dict[str, Any] = {}

    async def connect(self) -> None:
        await self._client.connect()
        self._connected = True
        # Sync immediately so buying power is available as soon as the platform starts,
        # then the refresh loop takes over for periodic updates.
        await self.sync_portfolio()
        self._portfolio_task = asyncio.create_task(self._portfolio_refresh_loop())
        self._log.info("public.com exec adapter connected")
        await self._bus.publish("execution.account.update", {"status": "connected"})

    async def disconnect(self) -> None:
        if self._portfolio_task:
            self._portfolio_task.cancel()
            try:
                await self._portfolio_task
            except asyncio.CancelledError:
                pass
        await self._client.disconnect()
        self._connected = False
        self._log.info("public.com exec adapter disconnected")

    async def submit_order(self, order: Order) -> Any:
        """Submit an order to Public.com."""
        order_id = order.order_id or str(uuid.uuid4())
        try:
            instrument_type = InstrumentType.EQUITY
            if order.symbol and len(order.symbol) > 10:
                instrument_type = InstrumentType.OPTION

            kwargs: dict[str, Any] = {
                "order_id": order_id,
                "instrument": OrderInstrument(symbol=order.symbol, type=instrument_type),
                "order_side": _SIDE_TO_SDK[order.side],
                "order_type": _TYPE_TO_SDK[order.order_type],
                "expiration": OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                "quantity": order.quantity,
            }
            if order.limit_price is not None:
                kwargs["limit_price"] = Decimal(str(order.limit_price))
            if order.stop_price is not None:
                kwargs["stop_price"] = Decimal(str(order.stop_price))
            if instrument_type == InstrumentType.OPTION:
                kwargs["open_close_indicator"] = OpenCloseIndicator.OPEN

            request = OrderRequest(**kwargs)
            async_order = await self._client.place_order(request)

            order.order_id = order_id
            order.status = "new"
            self._tracked_orders[order_id] = async_order

            await self._bus.publish("execution.order.submitted", {
                "order_id": order_id,
                "symbol": order.symbol,
                "side": str(order.side),
                "order_type": str(order.order_type),
                "quantity": order.quantity,
            })
            self._log.info("order submitted", order_id=order_id, symbol=order.symbol)

            asyncio.create_task(self._track_order(order_id, async_order))
            return async_order

        except RateLimitError as exc:
            self._log.warning("rate limited on order submit", retry_after=getattr(exc, "retry_after", None))
            await self._bus.publish("execution.order.error", {
                "order_id": order_id,
                "error": "rate_limited",
                "detail": str(exc),
            })
            raise
        except APIError as exc:
            self._log.error("API error on order submit", error=str(exc))
            await self._bus.publish("execution.order.error", {
                "order_id": order_id,
                "error": "api_error",
                "detail": str(exc),
            })
            raise

    async def submit_multileg_order(
        self,
        request: MultilegOrderRequest,
    ) -> Any:
        """Submit a multi-leg order to Public.com."""
        order_id = request.order_id or str(uuid.uuid4())
        try:
            async_order = await self._client.place_multileg_order(request)
            self._tracked_orders[order_id] = async_order

            await self._bus.publish("execution.order.submitted", {
                "order_id": order_id,
                "type": "multileg",
                "legs": len(request.legs),
            })
            self._log.info("multileg order submitted", order_id=order_id)

            asyncio.create_task(self._track_order(order_id, async_order))
            return async_order

        except APIError as exc:
            await self._bus.publish("execution.order.error", {
                "order_id": order_id,
                "error": "api_error",
                "detail": str(exc),
            })
            raise

    async def cancel_order(self, order_id: str) -> Any:
        """Cancel an order on Public.com."""
        try:
            await self._client.cancel_order(order_id)
            await self._bus.publish("execution.order.cancelled", {"order_id": order_id})
            self._log.info("order cancelled", order_id=order_id)
        except APIError as exc:
            await self._bus.publish("execution.order.error", {
                "order_id": order_id,
                "error": "cancel_failed",
                "detail": str(exc),
            })
            raise

    async def cancel_and_replace(self, request: CancelAndReplaceRequest) -> Any:
        """Cancel and replace an order."""
        try:
            async_order = await self._client.cancel_and_replace_order(request)
            new_order_id = getattr(async_order, "order_id", "")
            self._tracked_orders[new_order_id] = async_order

            await self._bus.publish("execution.order.submitted", {
                "order_id": new_order_id,
                "type": "cancel_and_replace",
            })
            asyncio.create_task(self._track_order(new_order_id, async_order))
            return async_order
        except APIError as exc:
            await self._bus.publish("execution.order.error", {
                "error": "cancel_replace_failed",
                "detail": str(exc),
            })
            raise

    async def get_positions(self) -> list[Position]:
        """Return cached positions from last portfolio sync."""
        return list(self._positions)

    async def get_account(self) -> dict[str, Any]:
        """Return cached account info from last portfolio sync."""
        return dict(self._account_info)

    async def perform_preflight(self, order: Order) -> Any:
        """Run preflight check for a single-leg order."""
        instrument_type = InstrumentType.EQUITY
        if order.symbol and len(order.symbol) > 10:
            instrument_type = InstrumentType.OPTION

        request = PreflightRequest(
            instrument=OrderInstrument(symbol=order.symbol, type=instrument_type),
            order_side=_SIDE_TO_SDK[order.side],
            order_type=_TYPE_TO_SDK[order.order_type],
            quantity=order.quantity,
            limit_price=Decimal(str(order.limit_price)) if order.limit_price else None,
        )
        return await self._client.perform_preflight(request)

    async def sync_portfolio(self) -> None:
        """Fetch portfolio from Public.com and update cached state."""
        try:
            portfolio = await self._client.get_portfolio()

            positions = []
            if hasattr(portfolio, "positions") and portfolio.positions:
                for pos in portfolio.positions:
                    positions.append(sdk_position_to_platform(pos))
            self._positions = positions

            account_data: dict[str, Any] = {}
            bp = getattr(portfolio, "buying_power", None)
            if bp is not None:
                account_data["buying_power_cash"] = float(getattr(bp, "cash_only_buying_power", 0) or 0)
                account_data["buying_power"] = float(getattr(bp, "buying_power", 0) or 0)
                account_data["buying_power_options"] = float(getattr(bp, "options_buying_power", 0) or 0)
            # equity is a list of PortfolioEquity objects broken down by asset type
            equity_list = getattr(portfolio, "equity", None)
            if equity_list:
                account_data["equity_total"] = sum(float(getattr(eq, "value", 0) or 0) for eq in equity_list)
                for eq in equity_list:
                    type_name = str(getattr(getattr(eq, "type", None), "value", "unknown")).lower()
                    account_data[f"equity_{type_name}"] = float(getattr(eq, "value", 0) or 0)
            self._account_info = account_data
            self._log.info("portfolio synced", positions=len(positions), account_keys=list(account_data.keys()))

            await self._bus.publish("execution.portfolio.update", {
                "positions": [p.model_dump(mode="json") for p in positions],
                "account": account_data,
            })
            await self._bus.publish("execution.account.update", account_data)

        except APIError as exc:
            self._log.error("portfolio sync failed", error=str(exc))
        except Exception as exc:
            self._log.error("portfolio sync unexpected error", error=str(exc))

    # ── Internal ──────────────────────────────────────────────────────

    async def _track_order(self, order_id: str, async_order: Any) -> None:
        """Track an order's status via polling until terminal."""
        _fill_published = False

        async def _publish_status(raw_status: Any) -> None:
            nonlocal _fill_published
            status_name = str(raw_status.name) if hasattr(raw_status, "name") else str(raw_status)
            status_upper = status_name.upper()
            if status_upper == "FILLED":
                _fill_published = True
                await self._bus.publish("execution.order.filled", {
                    "order_id": order_id,
                    "status": status_upper,
                })
            elif status_upper == "PARTIALLY_FILLED":
                await self._bus.publish("execution.order.partially_filled", {
                    "order_id": order_id,
                    "status": status_upper,
                })
            elif status_upper in ("CANCELLED", "CANCELED"):
                await self._bus.publish("execution.order.cancelled", {
                    "order_id": order_id,
                    "status": status_upper,
                })
            elif status_upper == "REJECTED":
                await self._bus.publish("execution.order.rejected", {
                    "order_id": order_id,
                    "status": status_upper,
                })

        try:
            async def on_update(update: Any) -> None:
                # SDK may use .status, .order_status, or .state — try all
                raw = (
                    getattr(update, "status", None)
                    or getattr(update, "order_status", None)
                    or getattr(update, "state", None)
                )
                if raw is None:
                    self._log.debug(
                        "order update with unknown status field",
                        order_id=order_id,
                        attrs=[a for a in dir(update) if not a.startswith("_")],
                    )
                    return
                await _publish_status(raw)

            await async_order.subscribe_updates(on_update)
            await async_order.wait_for_terminal_status(timeout=300)

            # Fallback: if the on_update callback never fired successfully, derive
            # the final status from the order object directly and publish now.
            if not _fill_published:
                raw = (
                    getattr(async_order, "status", None)
                    or getattr(async_order, "order_status", None)
                    or getattr(async_order, "state", None)
                )
                if raw is not None:
                    await _publish_status(raw)
                else:
                    # Last resort: assume FILLED since wait_for_terminal_status completed
                    self._log.warning(
                        "could not read terminal status from order object — assuming FILLED",
                        order_id=order_id,
                    )
                    await self._bus.publish("execution.order.filled", {
                        "order_id": order_id,
                        "status": "FILLED",
                    })
        except Exception as exc:
            self._log.warning("order tracking ended", order_id=order_id, error=str(exc))
        finally:
            self._tracked_orders.pop(order_id, None)

    async def _portfolio_refresh_loop(self) -> None:
        """Periodically refresh portfolio state."""
        while True:
            try:
                await asyncio.sleep(self._config.portfolio_refresh)
                await self.sync_portfolio()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.warning("portfolio refresh error", error=str(exc))
