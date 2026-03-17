"""Crypto execution adapter implementing ExecAdapter."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

from trading_platform.adapters.base import ExecAdapter
from trading_platform.adapters.crypto.client import CryptoClient
from trading_platform.adapters.crypto.config import CryptoConfig
from trading_platform.core.enums import AssetClass, OrderSide, OrderType
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
        self._order_details: dict[str, dict] = {}
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
            self._order_details[order_id] = {
                "symbol": order.symbol,
                "side": str(order.side.value if hasattr(order.side, "value") else order.side),
                "order_type": str(order.order_type.value if hasattr(order.order_type, "value") else order.order_type),
                "quantity": str(order.quantity),
                "asset_class": "crypto",
            }

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
        """Fetch crypto portfolio and update cached state.

        Crypto positions live in the same get_portfolio() response as equities.
        Filter by instrument type CRYPTO to isolate them.
        """
        try:
            portfolio = await self._client.get_portfolio()

            positions: list[Position] = []
            for pos in (getattr(portfolio, "positions", None) or []):
                instrument = getattr(pos, "instrument", None)
                inst_type = str(getattr(getattr(instrument, "type", None), "value", "")).upper()
                if inst_type != "CRYPTO":
                    continue
                symbol = getattr(instrument, "symbol", "") if instrument else ""
                quantity = Decimal(str(getattr(pos, "quantity", 0) or 0))
                market_value = float(getattr(pos, "current_value", 0) or 0)
                cost_basis = getattr(pos, "cost_basis", None)
                avg_price = float(getattr(cost_basis, "unit_cost", 0) or 0) if cost_basis else 0.0
                unrealized = float(getattr(cost_basis, "gain_value", 0) or 0) if cost_basis else 0.0
                side = "long" if quantity >= 0 else "short"
                positions.append(Position(
                    symbol=symbol,
                    quantity=abs(quantity),
                    avg_entry_price=avg_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized,
                    side=side,
                    asset_class=AssetClass.CRYPTO,
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
                        "crypto order update with unknown status field",
                        order_id=order_id,
                        attrs=[a for a in dir(update) if not a.startswith("_")],
                    )
                    return
                await _publish_status(raw)

            await async_order.subscribe_updates(on_update)
            await async_order.wait_for_terminal_status(timeout=300)

            # Fallback: if on_update never fired successfully, derive final status
            # from the order object directly.
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
                        "could not read terminal status from crypto order — assuming FILLED",
                        order_id=order_id,
                    )
                    await self._bus.publish("execution.order.filled", {
                        "order_id": order_id,
                        "status": "FILLED",
                    })
        except Exception as exc:
            self._log.warning("crypto order tracking ended", order_id=order_id, error=str(exc))
        finally:
            self._tracked_orders.pop(order_id, None)
            self._order_details.pop(order_id, None)

    async def _portfolio_refresh_loop(self) -> None:
        """Periodically refresh crypto portfolio state, reconnecting on repeated failures."""
        _consecutive_errors = 0
        _MAX_ERRORS_BEFORE_RECONNECT = 5
        while True:
            try:
                await asyncio.sleep(self._config.portfolio_refresh)
                await self.sync_portfolio()
                _consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _consecutive_errors += 1
                self._log.warning(
                    "crypto portfolio refresh error",
                    error=str(exc),
                    consecutive_errors=_consecutive_errors,
                )
                if _consecutive_errors >= _MAX_ERRORS_BEFORE_RECONNECT:
                    self._log.error(
                        "too many consecutive errors, attempting crypto adapter reconnect"
                    )
                    try:
                        await self._client.disconnect()
                        await self._client.connect()
                        _consecutive_errors = 0
                        self._log.info("crypto adapter reconnected successfully")
                    except Exception as reconn_exc:
                        self._log.error("crypto reconnect failed", error=str(reconn_exc))
