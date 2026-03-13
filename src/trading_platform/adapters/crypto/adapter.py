"""Crypto execution adapter implementing ExecAdapter."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

from trading_platform.adapters.base import ExecAdapter
from trading_platform.adapters.crypto.client import CryptoClient
from trading_platform.adapters.crypto.config import CryptoConfig
from trading_platform.core.enums import OrderSide, OrderType
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.core.models import Order, Position


class CryptoExecAdapter(ExecAdapter):
    """Execution adapter for crypto via Public.com SDK.

    Supports 24/7 trading — no market-hours checks.
    Handles fractional quantities via Decimal.
    """

    def __init__(self, config: CryptoConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._log = get_logger("crypto.adapter")
        self._client = CryptoClient(config)
        self._connected = False
        self._portfolio_task: asyncio.Task[None] | None = None
        self._tracked_orders: dict[str, Any] = {}
        self._positions: list[Position] = []
        self._account_info: dict[str, Any] = {}

    async def connect(self) -> None:
        await self._client.connect()
        self._connected = True
        self._portfolio_task = asyncio.create_task(self._portfolio_refresh_loop())
        self._log.info("crypto exec adapter connected")
        await self._bus.publish("execution.account.update", {"status": "connected", "asset_class": "crypto"})

    async def disconnect(self) -> None:
        if self._portfolio_task:
            self._portfolio_task.cancel()
            try:
                await self._portfolio_task
            except asyncio.CancelledError:
                pass
        await self._client.disconnect()
        self._connected = False
        self._log.info("crypto exec adapter disconnected")

    async def submit_order(self, order: Order) -> Any:
        """Submit a crypto order to Public.com."""
        order_id = order.order_id or str(uuid.uuid4())

        # Map platform side/type to SDK values
        side = "buy" if order.side == OrderSide.BUY else "sell"
        order_type_map = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP: "stop",
            OrderType.STOP_LIMIT: "stop_limit",
        }

        kwargs: dict[str, Any] = {
            "order_id": order_id,
            "symbol": order.symbol,
            "side": side,
            "order_type": order_type_map.get(order.order_type, "market"),
            "quantity": order.quantity,
        }
        if order.limit_price is not None:
            kwargs["limit_price"] = Decimal(str(order.limit_price))
        if order.stop_price is not None:
            kwargs["stop_price"] = Decimal(str(order.stop_price))

        try:
            async_order = await self._client.place_crypto_order(**kwargs)

            order.order_id = order_id
            order.status = "new"
            self._tracked_orders[order_id] = async_order

            await self._bus.publish("execution.order.submitted", {
                "order_id": order_id,
                "symbol": order.symbol,
                "side": str(order.side),
                "order_type": str(order.order_type),
                "quantity": str(order.quantity),
                "asset_class": "crypto",
            })
            self._log.info("crypto order submitted", order_id=order_id, symbol=order.symbol)

            asyncio.create_task(self._track_order(order_id, async_order))
            return async_order

        except Exception as exc:
            self._log.error("crypto order submit failed", error=str(exc))
            await self._bus.publish("execution.order.error", {
                "order_id": order_id,
                "error": "api_error",
                "detail": str(exc),
            })
            raise

    async def cancel_order(self, order_id: str) -> Any:
        """Cancel a crypto order."""
        try:
            await self._client.cancel_crypto_order(order_id)
            await self._bus.publish("execution.order.cancelled", {"order_id": order_id})
            self._log.info("crypto order cancelled", order_id=order_id)
        except Exception as exc:
            await self._bus.publish("execution.order.error", {
                "order_id": order_id,
                "error": "cancel_failed",
                "detail": str(exc),
            })
            raise

    async def get_positions(self) -> list[Position]:
        """Return cached crypto positions."""
        return list(self._positions)

    async def get_account(self) -> dict[str, Any]:
        """Return cached crypto account info."""
        return dict(self._account_info)

    async def sync_portfolio(self) -> None:
        """Fetch crypto portfolio and update cached state."""
        try:
            portfolio = await self._client.get_crypto_portfolio()

            positions: list[Position] = []
            if hasattr(portfolio, "positions") and portfolio.positions:
                for pos in portfolio.positions:
                    symbol = getattr(pos, "symbol", "")
                    quantity = Decimal(str(getattr(pos, "quantity", 0) or 0))
                    avg_price = float(getattr(pos, "average_price", 0) or 0)
                    market_value = float(getattr(pos, "market_value", 0) or 0)
                    unrealized = float(getattr(pos, "unrealized_pnl", 0) or 0)
                    side = "long" if quantity >= 0 else "short"
                    positions.append(Position(
                        symbol=symbol,
                        quantity=abs(quantity),
                        avg_entry_price=avg_price,
                        market_value=market_value,
                        unrealized_pnl=unrealized,
                        side=side,
                    ))
            self._positions = positions

            await self._bus.publish("execution.portfolio.update", {
                "positions": [p.model_dump(mode="json") for p in positions],
                "asset_class": "crypto",
            })
        except Exception as exc:
            self._log.error("crypto portfolio sync failed", error=str(exc))

    # ── Internal ──────────────────────────────────────────────────────

    async def _track_order(self, order_id: str, async_order: Any) -> None:
        """Track a crypto order's status until terminal."""
        try:
            async def on_update(update: Any) -> None:
                status_name = str(update.status.name) if hasattr(update.status, "name") else str(update.status)
                status_upper = status_name.upper()

                if status_upper == "FILLED":
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

            await async_order.subscribe_updates(on_update)
            await async_order.wait_for_terminal_status(timeout=300)
        except Exception as exc:
            self._log.warning("crypto order tracking ended", order_id=order_id, error=str(exc))
        finally:
            self._tracked_orders.pop(order_id, None)

    async def _portfolio_refresh_loop(self) -> None:
        """Periodically refresh crypto portfolio state."""
        while True:
            try:
                await asyncio.sleep(self._config.portfolio_refresh)
                await self.sync_portfolio()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.warning("crypto portfolio refresh error", error=str(exc))
