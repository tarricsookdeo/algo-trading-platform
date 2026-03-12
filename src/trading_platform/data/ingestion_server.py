"""Inbound data ingestion endpoints for REST and WebSocket.

These endpoints are added to the dashboard FastAPI app to accept
external data via REST POST or WebSocket streaming.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from trading_platform.core.logging import get_logger
from trading_platform.core.models import Bar, QuoteTick, TradeTick
from trading_platform.data.manager import DataManager

log = get_logger("data.ingestion")


def mount_ingestion_routes(app: FastAPI, data_manager: DataManager) -> None:
    """Add data ingestion REST and WebSocket routes to the app."""

    @app.post("/api/data/bars")
    async def ingest_bars(body: dict[str, Any] | list[dict[str, Any]]) -> JSONResponse:
        items = body if isinstance(body, list) else [body]
        if len(items) > data_manager._config.max_bars_per_request:
            return JSONResponse(
                {"error": f"max {data_manager._config.max_bars_per_request} bars per request"},
                status_code=400,
            )
        count = 0
        for item in items:
            try:
                bar = Bar(**item)
                await data_manager.publish_bar(bar.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                log.warning("invalid bar data", error=str(exc))
        return JSONResponse({"ingested": count})

    @app.post("/api/data/quotes")
    async def ingest_quotes(body: dict[str, Any] | list[dict[str, Any]]) -> JSONResponse:
        items = body if isinstance(body, list) else [body]
        count = 0
        for item in items:
            try:
                quote = QuoteTick(**item)
                await data_manager.publish_quote(quote.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                log.warning("invalid quote data", error=str(exc))
        return JSONResponse({"ingested": count})

    @app.post("/api/data/trades")
    async def ingest_trades(body: dict[str, Any] | list[dict[str, Any]]) -> JSONResponse:
        items = body if isinstance(body, list) else [body]
        count = 0
        for item in items:
            try:
                trade = TradeTick(**item)
                await data_manager.publish_trade(trade.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                log.warning("invalid trade data", error=str(exc))
        return JSONResponse({"ingested": count})

    @app.get("/api/data/status")
    async def data_status() -> JSONResponse:
        return JSONResponse(data_manager.get_ingestion_stats())

    @app.get("/api/data/providers")
    async def data_providers() -> JSONResponse:
        return JSONResponse({"providers": data_manager.get_provider_status()})

    @app.websocket("/ws/data")
    async def ws_data_ingest(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json({"error": "invalid JSON"})
                    continue

                msg_type = msg.get("type")
                data = msg.get("data", {})

                if msg_type == "bar":
                    bar = Bar(**data)
                    await data_manager.publish_bar(bar.model_dump(mode="json"))
                elif msg_type == "quote":
                    quote = QuoteTick(**data)
                    await data_manager.publish_quote(quote.model_dump(mode="json"))
                elif msg_type == "trade":
                    trade = TradeTick(**data)
                    await data_manager.publish_trade(trade.model_dump(mode="json"))
                else:
                    await ws.send_json({"error": f"unknown type: {msg_type}"})
                    continue

                await ws.send_json({"status": "ok", "type": msg_type})
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws data ingestion error")
