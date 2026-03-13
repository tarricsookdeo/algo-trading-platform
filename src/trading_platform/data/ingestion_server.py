"""Inbound data ingestion endpoints for REST and WebSocket.

These endpoints are added to the dashboard FastAPI app to accept
external data via REST POST or WebSocket streaming.  Includes batch
endpoints and WebSocket batch-frame support for high-throughput ingestion.

Supports both JSON and MessagePack serialization:
- REST: Content-Type header selects format (application/json or application/x-msgpack)
- WebSocket: binary frames = msgpack, text frames = JSON
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from trading_platform.core.logging import get_logger
from trading_platform.core.models import Bar, QuoteTick, TradeTick
from trading_platform.data.manager import DataManager
from trading_platform.data.serialization import (
    Format,
    deserialize,
    detect_format,
    serialize,
)

log = get_logger("data.ingestion")


def _make_response(data: dict[str, Any], accept: str | None, status_code: int = 200) -> Response:
    """Build a Response in the format requested by the Accept header."""
    fmt = detect_format(accept)
    if fmt == Format.MSGPACK:
        return Response(
            content=serialize(data, fmt),
            media_type="application/x-msgpack",
            status_code=status_code,
        )
    return JSONResponse(data, status_code=status_code)


async def _parse_body(request: Request) -> Any:
    """Parse request body based on Content-Type header."""
    fmt = detect_format(request.headers.get("content-type"))
    raw = await request.body()
    return deserialize(raw, fmt)


def mount_ingestion_routes(app: FastAPI, data_manager: DataManager) -> None:
    """Add data ingestion REST and WebSocket routes to the app."""

    # ── Single / small-batch REST endpoints ──────────────────────────────

    @app.post("/api/data/bars")
    async def ingest_bars(request: Request) -> Response:
        body = await _parse_body(request)
        accept = request.headers.get("accept")
        items = body if isinstance(body, list) else [body]
        if len(items) > data_manager._config.max_bars_per_request:
            return _make_response(
                {"error": f"max {data_manager._config.max_bars_per_request} bars per request"},
                accept,
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
        return _make_response({"ingested": count}, accept)

    @app.post("/api/data/quotes")
    async def ingest_quotes(request: Request) -> Response:
        body = await _parse_body(request)
        accept = request.headers.get("accept")
        items = body if isinstance(body, list) else [body]
        count = 0
        for item in items:
            try:
                quote = QuoteTick(**item)
                await data_manager.publish_quote(quote.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                log.warning("invalid quote data", error=str(exc))
        return _make_response({"ingested": count}, accept)

    @app.post("/api/data/trades")
    async def ingest_trades(request: Request) -> Response:
        body = await _parse_body(request)
        accept = request.headers.get("accept")
        items = body if isinstance(body, list) else [body]
        count = 0
        for item in items:
            try:
                trade = TradeTick(**item)
                await data_manager.publish_trade(trade.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                log.warning("invalid trade data", error=str(exc))
        return _make_response({"ingested": count}, accept)

    # ── Batch REST endpoints ─────────────────────────────────────────────

    @app.post("/api/data/bars/batch")
    async def ingest_bars_batch(request: Request) -> Response:
        body = await _parse_body(request)
        accept = request.headers.get("accept")
        if not isinstance(body, list):
            return _make_response({"error": "expected a list"}, accept, status_code=400)
        if len(body) > data_manager._config.max_bars_per_request:
            return _make_response(
                {"error": f"max {data_manager._config.max_bars_per_request} bars per request"},
                accept,
                status_code=400,
            )
        count = 0
        errors = 0
        for item in body:
            try:
                bar = Bar(**item)
                await data_manager.publish_bar(bar.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                errors += 1
                log.warning("invalid bar data in batch", error=str(exc))
        return _make_response({"ingested": count, "errors": errors}, accept)

    @app.post("/api/data/quotes/batch")
    async def ingest_quotes_batch(request: Request) -> Response:
        body = await _parse_body(request)
        accept = request.headers.get("accept")
        if not isinstance(body, list):
            return _make_response({"error": "expected a list"}, accept, status_code=400)
        count = 0
        errors = 0
        for item in body:
            try:
                quote = QuoteTick(**item)
                await data_manager.publish_quote(quote.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                errors += 1
                log.warning("invalid quote data in batch", error=str(exc))
        return _make_response({"ingested": count, "errors": errors}, accept)

    @app.post("/api/data/trades/batch")
    async def ingest_trades_batch(request: Request) -> Response:
        body = await _parse_body(request)
        accept = request.headers.get("accept")
        if not isinstance(body, list):
            return _make_response({"error": "expected a list"}, accept, status_code=400)
        count = 0
        errors = 0
        for item in body:
            try:
                trade = TradeTick(**item)
                await data_manager.publish_trade(trade.model_dump(mode="json"))
                count += 1
            except Exception as exc:
                errors += 1
                log.warning("invalid trade data in batch", error=str(exc))
        return _make_response({"ingested": count, "errors": errors}, accept)

    # ── Status endpoints ─────────────────────────────────────────────────

    @app.get("/api/data/status")
    async def data_status() -> JSONResponse:
        return JSONResponse(data_manager.get_ingestion_stats())

    @app.get("/api/data/providers")
    async def data_providers() -> JSONResponse:
        return JSONResponse({"providers": data_manager.get_provider_status()})

    # ── WebSocket ingestion (supports single + batch frames) ─────────────
    # Text frames → JSON, Binary frames → MessagePack

    @app.websocket("/ws/data")
    async def ws_data_ingest(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                ws_msg = await ws.receive()

                # Determine format from frame type
                if "bytes" in ws_msg and ws_msg["bytes"]:
                    # Binary frame → msgpack
                    try:
                        msg = deserialize(ws_msg["bytes"], Format.MSGPACK)
                    except Exception:
                        await ws.send_json({"error": "invalid msgpack"})
                        continue
                    response_fmt = Format.MSGPACK
                elif "text" in ws_msg and ws_msg["text"]:
                    # Text frame → JSON
                    try:
                        msg = json.loads(ws_msg["text"])
                    except json.JSONDecodeError:
                        await ws.send_json({"error": "invalid JSON"})
                        continue
                    response_fmt = Format.JSON
                else:
                    continue

                # Batch frame: array of messages
                if isinstance(msg, list):
                    results = []
                    for item in msg:
                        result = await _process_ws_message(item, data_manager)
                        results.append(result)
                    resp = {"status": "ok", "batch": True, "results": results}
                    if response_fmt == Format.MSGPACK:
                        await ws.send_bytes(serialize(resp, Format.MSGPACK))
                    else:
                        await ws.send_json(resp)
                    continue

                # Single message
                result = await _process_ws_message(msg, data_manager)
                if "error" in result:
                    resp = result
                else:
                    resp = {"status": "ok", "type": result.get("type", "")}

                if response_fmt == Format.MSGPACK:
                    await ws.send_bytes(serialize(resp, Format.MSGPACK))
                else:
                    await ws.send_json(resp)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws data ingestion error")


async def _process_ws_message(
    msg: dict[str, Any], data_manager: DataManager
) -> dict[str, Any]:
    """Process a single WS ingestion message, returning a result dict."""
    msg_type = msg.get("type")
    data = msg.get("data", {})

    try:
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
            return {"error": f"unknown type: {msg_type}"}
    except Exception as exc:
        return {"error": str(exc), "type": msg_type}

    return {"type": msg_type, "status": "ok"}
