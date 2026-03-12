"""Alpaca WebSocket streaming clients for stock (SIP) and options (OPRA) data.

Uses the `websockets` library. Each stream class manages its own connection,
authentication, subscriptions, auto-reconnect, and heartbeat monitoring.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import msgpack
import websockets
from websockets.asyncio.client import ClientConnection

from trading_platform.adapters.alpaca.config import AlpacaConfig
from trading_platform.adapters.alpaca.parse import (
    parse_luld,
    parse_option_quote,
    parse_option_trade,
    parse_stock_bar,
    parse_stock_quote,
    parse_stock_trade,
    parse_trading_status,
)
from trading_platform.core.enums import Channel
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger


class AlpacaStockStream:
    """WebSocket client for Alpaca SIP stock data.

    Connects to wss://stream.data.alpaca.markets/v2/sip, authenticates,
    subscribes, and dispatches parsed events onto the EventBus.
    """

    def __init__(self, config: AlpacaConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._log = get_logger("alpaca.stock_stream")
        self._ws: ClientConnection | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

        # Subscriptions
        self._trade_symbols: set[str] = set()
        self._quote_symbols: set[str] = set()
        self._bar_symbols: set[str] = set()

        # Metrics
        self.messages_received: int = 0
        self.last_message_time: float = 0.0
        self.reconnect_count: int = 0

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running

    async def start(self) -> None:
        """Start the stream in a background task."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Gracefully disconnect."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._log.info("stock stream stopped")

    async def subscribe(
        self,
        trades: list[str] | None = None,
        quotes: list[str] | None = None,
        bars: list[str] | None = None,
    ) -> None:
        """Subscribe to channels. Sends immediately if connected, queues otherwise."""
        if trades:
            self._trade_symbols.update(trades)
        if quotes:
            self._quote_symbols.update(quotes)
        if bars:
            self._bar_symbols.update(bars)
        if self._ws:
            await self._send_subscription()

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe given symbols from all channels."""
        sym_set = set(symbols)
        self._trade_symbols -= sym_set
        self._quote_symbols -= sym_set
        self._bar_symbols -= sym_set
        if self._ws:
            msg = json.dumps({
                "action": "unsubscribe",
                "trades": symbols,
                "quotes": symbols,
                "bars": symbols,
            })
            await self._ws.send(msg)

    # ── Internal ──────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main loop with exponential-backoff reconnect."""
        backoff = 1.0
        while self._running:
            try:
                await self._connect_and_listen()
                backoff = 1.0  # reset on clean disconnect
            except (
                websockets.ConnectionClosed,
                websockets.InvalidHandshake,
                OSError,
            ) as exc:
                self.reconnect_count += 1
                self._log.warning(
                    "stock stream disconnected, reconnecting",
                    error=str(exc),
                    backoff=backoff,
                )
                await self._bus.publish(
                    Channel.SYSTEM,
                    {"component": "alpaca.stock_stream", "message": f"reconnecting in {backoff}s", "level": "warn"},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.error("stock stream unexpected error", error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _connect_and_listen(self) -> None:
        """Single connection lifecycle: connect, auth, subscribe, consume."""
        url = self._config.stock_ws_url
        self._log.info("connecting to stock stream", url=url)

        async with websockets.connect(url) as ws:
            self._ws = ws

            # Wait for connected message
            raw = await ws.recv()
            msgs = json.loads(raw)
            self._log.debug("stock stream connected", msgs=msgs)

            # Authenticate
            auth_msg = json.dumps({
                "action": "auth",
                "key": self._config.api_key,
                "secret": self._config.api_secret,
            })
            await ws.send(auth_msg)
            raw = await ws.recv()
            msgs = json.loads(raw)
            for m in msgs:
                if m.get("T") == "error":
                    raise RuntimeError(f"Auth failed: {m}")
            self._log.info("stock stream authenticated")

            await self._bus.publish(
                Channel.SYSTEM,
                {"component": "alpaca.stock_stream", "message": "authenticated", "level": "info"},
            )

            # Subscribe to configured symbols
            await self._send_subscription()

            # Consume messages
            async for raw in ws:
                if not self._running:
                    break
                self.messages_received += 1
                self.last_message_time = time.monotonic()
                msgs = json.loads(raw)
                for m in msgs:
                    await self._dispatch(m)

        self._ws = None

    async def _send_subscription(self) -> None:
        """Send subscription message for all tracked symbols."""
        if not self._ws:
            return
        msg = json.dumps({
            "action": "subscribe",
            "trades": sorted(self._trade_symbols),
            "quotes": sorted(self._quote_symbols),
            "bars": sorted(self._bar_symbols),
        })
        await self._ws.send(msg)
        self._log.info(
            "stock subscriptions sent",
            trades=len(self._trade_symbols),
            quotes=len(self._quote_symbols),
            bars=len(self._bar_symbols),
        )

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """Route a parsed message to the correct event bus channel."""
        t = msg.get("T")
        if t == "t":
            await self._bus.publish(Channel.TRADE, parse_stock_trade(msg))
        elif t == "q":
            await self._bus.publish(Channel.QUOTE, parse_stock_quote(msg))
        elif t in ("b", "d", "u"):
            await self._bus.publish(Channel.BAR, parse_stock_bar(msg))
        elif t == "s":
            await self._bus.publish(Channel.STATUS, parse_trading_status(msg))
        elif t == "l":
            await self._bus.publish(Channel.STATUS, parse_luld(msg))
        elif t == "subscription":
            self._log.info("subscription confirmed", data=msg)
        elif t == "error":
            self._log.error("stream error", data=msg)
            await self._bus.publish(Channel.ERROR, msg)
        elif t == "success":
            pass  # connected / authenticated confirmations


class AlpacaOptionsStream:
    """WebSocket client for Alpaca OPRA options data.

    Same pattern as the stock stream, but uses msgpack encoding and has
    different channel availability (trades + quotes only, no bars).
    """

    MAX_QUOTE_SUBSCRIPTIONS = 1000

    def __init__(self, config: AlpacaConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._log = get_logger("alpaca.options_stream")
        self._ws: ClientConnection | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

        self._trade_symbols: set[str] = set()
        self._quote_symbols: set[str] = set()

        self.messages_received: int = 0
        self.last_message_time: float = 0.0
        self.reconnect_count: int = 0

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._log.info("options stream stopped")

    async def subscribe(
        self,
        trades: list[str] | None = None,
        quotes: list[str] | None = None,
    ) -> None:
        if trades:
            self._trade_symbols.update(trades)
        if quotes:
            # Enforce 1000 quote limit
            new_quotes = self._quote_symbols | set(quotes)
            if len(new_quotes) > self.MAX_QUOTE_SUBSCRIPTIONS:
                self._log.warning(
                    "quote subscription limit reached",
                    requested=len(new_quotes),
                    max=self.MAX_QUOTE_SUBSCRIPTIONS,
                )
                return
            self._quote_symbols = new_quotes
        if self._ws:
            await self._send_subscription()

    async def unsubscribe(self, symbols: list[str]) -> None:
        sym_set = set(symbols)
        self._trade_symbols -= sym_set
        self._quote_symbols -= sym_set
        if self._ws:
            msg = msgpack.packb({
                "action": "unsubscribe",
                "trades": symbols,
                "quotes": symbols,
            })
            await self._ws.send(msg)

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                await self._connect_and_listen()
                backoff = 1.0
            except (
                websockets.ConnectionClosed,
                websockets.InvalidHandshake,
                OSError,
            ) as exc:
                self.reconnect_count += 1
                self._log.warning(
                    "options stream disconnected, reconnecting",
                    error=str(exc),
                    backoff=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.error("options stream unexpected error", error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _connect_and_listen(self) -> None:
        url = self._config.options_ws_url
        self._log.info("connecting to options stream", url=url)

        async with websockets.connect(url) as ws:
            self._ws = ws

            # Wait for connected message (msgpack)
            raw = await ws.recv()
            msgs = msgpack.unpackb(raw, raw=False) if isinstance(raw, bytes) else json.loads(raw)
            self._log.debug("options stream connected", msgs=msgs)

            # Authenticate
            auth_payload = msgpack.packb({
                "action": "auth",
                "key": self._config.api_key,
                "secret": self._config.api_secret,
            })
            await ws.send(auth_payload)
            raw = await ws.recv()
            msgs = msgpack.unpackb(raw, raw=False) if isinstance(raw, bytes) else json.loads(raw)
            if isinstance(msgs, list):
                for m in msgs:
                    if isinstance(m, dict) and m.get("T") == "error":
                        raise RuntimeError(f"Options auth failed: {m}")
            self._log.info("options stream authenticated")

            await self._bus.publish(
                Channel.SYSTEM,
                {"component": "alpaca.options_stream", "message": "authenticated", "level": "info"},
            )

            await self._send_subscription()

            # Consume
            async for raw in ws:
                if not self._running:
                    break
                self.messages_received += 1
                self.last_message_time = time.monotonic()
                if isinstance(raw, bytes):
                    msgs = msgpack.unpackb(raw, raw=False)
                else:
                    msgs = json.loads(raw)
                if not isinstance(msgs, list):
                    msgs = [msgs]
                for m in msgs:
                    await self._dispatch(m)

        self._ws = None

    async def _send_subscription(self) -> None:
        if not self._ws:
            return
        payload = msgpack.packb({
            "action": "subscribe",
            "trades": sorted(self._trade_symbols),
            "quotes": sorted(self._quote_symbols),
        })
        await self._ws.send(payload)
        self._log.info(
            "options subscriptions sent",
            trades=len(self._trade_symbols),
            quotes=len(self._quote_symbols),
        )

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            return
        t = msg.get("T")
        if t == "t":
            await self._bus.publish(Channel.TRADE, parse_option_trade(msg))
        elif t == "q":
            await self._bus.publish(Channel.QUOTE, parse_option_quote(msg))
        elif t == "subscription":
            self._log.info("options subscription confirmed", data=msg)
        elif t == "error":
            self._log.error("options stream error", data=msg)
            await self._bus.publish(Channel.ERROR, msg)
        elif t == "success":
            pass
