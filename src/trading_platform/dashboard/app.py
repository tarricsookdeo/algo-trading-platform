"""FastAPI dashboard application.

Serves the static HTML dashboard and exposes REST + WebSocket endpoints
for real-time monitoring and subscription management.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger
from trading_platform.dashboard.ws import DashboardWSManager

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    event_bus: EventBus,
    adapter: Any = None,
) -> tuple[FastAPI, DashboardWSManager]:
    """Create and configure the FastAPI application.

    Returns the app and the WS manager so the platform can start/stop them.
    """
    app = FastAPI(title="Algo Trading Platform", docs_url=None, redoc_url=None)
    ws_manager = DashboardWSManager(event_bus)
    log = get_logger("dashboard.app")

    # Store adapter reference for subscription management
    app.state.adapter = adapter
    app.state.ws_manager = ws_manager
    app.state.event_bus = event_bus

    # ── Static ────────────────────────────────────────────────────────

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    # ── REST Endpoints ────────────────────────────────────────────────

    @app.get("/api/status")
    async def status() -> JSONResponse:
        bus = app.state.event_bus
        adp = app.state.adapter
        data: dict[str, Any] = {
            "status": "running",
            "total_events": bus.total_published,
            "events_per_second": round(bus.events_per_second(), 1),
            "subscribers": bus.subscriber_count,
        }
        if adp:
            data["stock_stream"] = {
                "connected": adp.stock_stream.is_connected,
                "messages": adp.stock_stream.messages_received,
                "reconnects": adp.stock_stream.reconnect_count,
            }
            data["options_stream"] = {
                "connected": adp.options_stream.is_connected,
                "messages": adp.options_stream.messages_received,
                "reconnects": adp.options_stream.reconnect_count,
            }
        return JSONResponse(data)

    @app.get("/api/subscriptions")
    async def get_subscriptions() -> JSONResponse:
        adp = app.state.adapter
        if not adp:
            return JSONResponse({"symbols": []})
        symbols = sorted(adp.stock_stream._trade_symbols | adp.stock_stream._quote_symbols)
        return JSONResponse({"symbols": symbols})

    @app.post("/api/subscribe")
    async def subscribe_symbol(body: dict[str, Any]) -> JSONResponse:
        symbol = body.get("symbol", "").upper().strip()
        if not symbol:
            return JSONResponse({"error": "symbol required"}, status_code=400)
        adp = app.state.adapter
        if adp:
            await adp.subscribe_trades([symbol])
            await adp.subscribe_quotes([symbol])
            await adp.subscribe_bars([symbol])
            log.info("subscribed to symbol via API", symbol=symbol)
        return JSONResponse({"status": "subscribed", "symbol": symbol})

    @app.delete("/api/subscribe/{symbol}")
    async def unsubscribe_symbol(symbol: str) -> JSONResponse:
        symbol = symbol.upper().strip()
        adp = app.state.adapter
        if adp:
            await adp.unsubscribe([symbol])
            log.info("unsubscribed from symbol via API", symbol=symbol)
        return JSONResponse({"status": "unsubscribed", "symbol": symbol})

    # ── WebSocket ─────────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws_manager.connect(ws)
        try:
            while True:
                # Keep connection alive; client can send pings
                await ws.receive_text()
        except WebSocketDisconnect:
            await ws_manager.disconnect(ws)
        except Exception:
            await ws_manager.disconnect(ws)

    return app, ws_manager
