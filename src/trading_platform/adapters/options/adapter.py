"""Options execution adapter implementing ExecAdapter."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from public_api_sdk.models import (
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
    OrderType as SDKOrderType,
    PreflightMultiLegRequest,
    PreflightRequest,
    TimeInForce,
)
from public_api_sdk.exceptions import APIError, RateLimitError

from trading_platform.adapters.base import ExecAdapter
from trading_platform.adapters.options.client import OptionsClient
from trading_platform.adapters.options.config import OptionsConfig
from trading_platform.core.enums import ContractType, OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import MultiLegOrder, Order, Position

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


class OptionsExecAdapter(ExecAdapter):
    """Execution adapter for options via Public.com SDK."""

    def __init__(self, config: OptionsConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._log = get_logger("options.adapter")
        self._client = OptionsClient(config)
        self._connected = False
        self._portfolio_task: asyncio.Task[None] | None = None
        self._tracked_orders: dict[str, Any] = {}
        self._positions: list[Position] = []
        self._account_info: dict[str, Any] = {}

    async def connect(self) -> None:
        await self._client.connect()
        self._connected = True
        self._portfolio_task = asyncio.create_task(self._portfolio_refresh_loop())
        self._log.info("options exec adapter connected")
        await self._bus.publish(
            "execution.account.update",
            {"status": "connected", "asset_class": "option"},
        )

    async def disconnect(self) -> None:
        if self._portfolio_task:
            self._portfolio_task.cancel()
            try:
                await self._portfolio_task
            except asyncio.CancelledError:
                pass
        await self._client.disconnect()
        self._connected = False
        self._log.info("options exec adapter disconnected")

    async def submit_order(self, order: Order) -> Any:
        """Submit a single-leg option order."""
        return await self.submit_option_order(order)

    async def submit_option_order(self, order: Order) -> Any:
        """Submit a single-leg option order to Public.com."""
        order_id = order.order_id or str(uuid.uuid4())
        try:
            symbol = order.option_symbol or order.symbol

            kwargs: dict[str, Any] = {
                "order_id": order_id,
                "instrument": OrderInstrument(
                    symbol=symbol, type=InstrumentType.OPTION
                ),
                "order_side": _SIDE_TO_SDK[order.side],
                "order_type": _TYPE_TO_SDK[order.order_type],
                "expiration": OrderExpirationRequest(
                    time_in_force=TimeInForce.DAY
                ),
                "quantity": order.quantity,
                "open_close_indicator": OpenCloseIndicator.OPEN,
            }
            if order.limit_price is not None:
                kwargs["limit_price"] = Decimal(str(order.limit_price))
            if order.stop_price is not None:
                kwargs["stop_price"] = Decimal(str(order.stop_price))

            request = OrderRequest(**kwargs)
            async_order = await self._client.place_option_order(request)

            order.order_id = order_id
            order.status = "new"
            self._tracked_orders[order_id] = async_order

            await self._bus.publish(
                "execution.order.submitted",
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": str(order.side),
                    "order_type": str(order.order_type),
                    "quantity": str(order.quantity),
                    "asset_class": "option",
                    "contract_type": str(order.contract_type) if order.contract_type else None,
                    "strike_price": str(order.strike_price) if order.strike_price else None,
                },
            )
            self._log.info(
                "option order submitted",
                order_id=order_id,
                symbol=symbol,
            )

            asyncio.create_task(self._track_order(order_id, async_order))
            return async_order

        except RateLimitError as exc:
            self._log.warning(
                "rate limited on option order submit",
                retry_after=getattr(exc, "retry_after", None),
            )
            await self._bus.publish(
                "execution.order.error",
                {
                    "order_id": order_id,
                    "error": "rate_limited",
                    "detail": str(exc),
                },
            )
            raise
        except APIError as exc:
            self._log.error("API error on option order submit", error=str(exc))
            await self._bus.publish(
                "execution.order.error",
                {
                    "order_id": order_id,
                    "error": "api_error",
                    "detail": str(exc),
                },
            )
            raise

    async def submit_multileg_order(self, multileg: MultiLegOrder) -> Any:
        """Submit a multi-leg options order to Public.com."""
        order_id = multileg.id if multileg.id else str(uuid.uuid4())
        # SDK requires a valid UUID for order_id
        try:
            uuid.UUID(order_id)
        except ValueError:
            order_id = str(uuid.uuid4())
        try:
            legs = []
            for leg in multileg.legs:
                symbol = leg.option_symbol or leg.symbol
                leg_request = OrderLegRequest(
                    instrument=LegInstrument(
                        symbol=symbol,
                        type=LegInstrumentType.OPTION,
                    ),
                    side=_SIDE_TO_SDK[leg.side],
                    ratio_quantity=int(leg.quantity),
                    open_close_indicator=OpenCloseIndicator.OPEN,
                )
                legs.append(leg_request)

            # SDK requires LIMIT for multi-leg orders
            limit_price = multileg.net_debit_or_credit or Decimal("0")

            # Total quantity across all legs
            total_quantity = sum(int(leg.quantity) for leg in multileg.legs)

            request = MultilegOrderRequest(
                order_id=order_id,
                legs=legs,
                type=SDKOrderType.LIMIT,
                quantity=total_quantity,
                expiration=OrderExpirationRequest(
                    time_in_force=TimeInForce.DAY
                ),
                limit_price=limit_price,
            )

            async_order = await self._client.place_multileg_order(request)
            self._tracked_orders[order_id] = async_order

            await self._bus.publish(
                "execution.order.submitted",
                {
                    "order_id": order_id,
                    "type": "multileg",
                    "strategy_type": multileg.strategy_type,
                    "legs": len(multileg.legs),
                    "asset_class": "option",
                },
            )
            self._log.info(
                "multileg option order submitted",
                order_id=order_id,
                strategy=multileg.strategy_type,
                legs=len(multileg.legs),
            )

            asyncio.create_task(self._track_order(order_id, async_order))
            return async_order

        except APIError as exc:
            await self._bus.publish(
                "execution.order.error",
                {
                    "order_id": order_id,
                    "error": "api_error",
                    "detail": str(exc),
                },
            )
            raise

    async def cancel_order(self, order_id: str) -> Any:
        """Cancel an option order."""
        return await self.cancel_option_order(order_id)

    async def cancel_option_order(self, order_id: str) -> Any:
        """Cancel an option order on Public.com."""
        try:
            await self._client.cancel_order(order_id)
            await self._bus.publish(
                "execution.order.cancelled", {"order_id": order_id}
            )
            self._log.info("option order cancelled", order_id=order_id)
        except APIError as exc:
            await self._bus.publish(
                "execution.order.error",
                {
                    "order_id": order_id,
                    "error": "cancel_failed",
                    "detail": str(exc),
                },
            )
            raise

    async def get_positions(self) -> list[Position]:
        """Return cached options positions."""
        return list(self._positions)

    async def get_option_positions(self) -> list[Position]:
        """Get open options positions."""
        return list(self._positions)

    async def get_account(self) -> dict[str, Any]:
        """Return cached account info."""
        return dict(self._account_info)

    async def preflight_option_order(self, order: Order) -> Any:
        """Preflight check for a single-leg option order."""
        symbol = order.option_symbol or order.symbol
        request = PreflightRequest(
            instrument=OrderInstrument(
                symbol=symbol, type=InstrumentType.OPTION
            ),
            order_side=_SIDE_TO_SDK[order.side],
            order_type=_TYPE_TO_SDK[order.order_type],
            expiration=OrderExpirationRequest(
                time_in_force=TimeInForce.DAY
            ),
            quantity=order.quantity,
            limit_price=(
                Decimal(str(order.limit_price)) if order.limit_price else None
            ),
        )
        return await self._client.perform_preflight(request)

    async def get_option_chain(self, underlying: str) -> Any:
        """Fetch option chain for an underlying symbol."""
        return await self._client.get_option_chain(underlying)

    async def get_option_expirations(self, underlying: str) -> Any:
        """Fetch available expirations for an underlying symbol."""
        return await self._client.get_option_expirations(underlying)

    async def sync_portfolio(self) -> None:
        """Fetch options portfolio and update cached state."""
        try:
            portfolio = await self._client.get_option_portfolio()

            positions: list[Position] = []
            if hasattr(portfolio, "positions") and portfolio.positions:
                for pos in portfolio.positions:
                    instrument_type = getattr(pos, "instrument_type", "")
                    if str(instrument_type).upper() not in ("OPTION", "OPTIONS"):
                        continue
                    symbol = getattr(pos, "symbol", "")
                    quantity = Decimal(str(getattr(pos, "quantity", 0) or 0))
                    avg_price = float(getattr(pos, "average_price", 0) or 0)
                    market_value = float(
                        getattr(pos, "market_value", 0) or 0
                    )
                    unrealized = float(
                        getattr(pos, "unrealized_pnl", 0) or 0
                    )
                    side = "long" if quantity >= 0 else "short"
                    positions.append(
                        Position(
                            symbol=symbol,
                            quantity=abs(quantity),
                            avg_entry_price=avg_price,
                            market_value=market_value,
                            unrealized_pnl=unrealized,
                            side=side,
                        )
                    )
            self._positions = positions

            await self._bus.publish(
                "execution.portfolio.update",
                {
                    "positions": [
                        p.model_dump(mode="json") for p in positions
                    ],
                    "asset_class": "option",
                },
            )
        except Exception as exc:
            self._log.error("options portfolio sync failed", error=str(exc))

    # ── Internal ──────────────────────────────────────────────────────

    async def _track_order(self, order_id: str, async_order: Any) -> None:
        """Track an option order's status until terminal."""
        try:

            async def on_update(update: Any) -> None:
                status_name = (
                    str(update.status.name)
                    if hasattr(update.status, "name")
                    else str(update.status)
                )
                status_upper = status_name.upper()

                if status_upper == "FILLED":
                    await self._bus.publish(
                        "execution.order.filled",
                        {"order_id": order_id, "status": status_upper},
                    )
                elif status_upper == "PARTIALLY_FILLED":
                    await self._bus.publish(
                        "execution.order.partially_filled",
                        {"order_id": order_id, "status": status_upper},
                    )
                elif status_upper in ("CANCELLED", "CANCELED"):
                    await self._bus.publish(
                        "execution.order.cancelled",
                        {"order_id": order_id, "status": status_upper},
                    )
                elif status_upper == "REJECTED":
                    await self._bus.publish(
                        "execution.order.rejected",
                        {"order_id": order_id, "status": status_upper},
                    )

            await async_order.subscribe_updates(on_update)
            await async_order.wait_for_terminal_status(timeout=300)
        except Exception as exc:
            self._log.warning(
                "option order tracking ended",
                order_id=order_id,
                error=str(exc),
            )
        finally:
            self._tracked_orders.pop(order_id, None)

    async def _portfolio_refresh_loop(self) -> None:
        """Periodically refresh options portfolio state."""
        while True:
            try:
                await asyncio.sleep(self._config.portfolio_refresh)
                await self.sync_portfolio()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.warning(
                    "options portfolio refresh error", error=str(exc)
                )
