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
    exec_adapter: Any = None,
    strategy_manager: Any = None,
    risk_manager: Any = None,
) -> tuple[FastAPI, DashboardWSManager]:
    """Create and configure the FastAPI application.

    Returns the app and the WS manager so the platform can start/stop them.
    """
    app = FastAPI(title="Algo Trading Platform", docs_url=None, redoc_url=None)
    ws_manager = DashboardWSManager(event_bus)
    log = get_logger("dashboard.app")

    # Store references for endpoint handlers
    app.state.adapter = adapter
    app.state.exec_adapter = exec_adapter
    app.state.strategy_manager = strategy_manager
    app.state.risk_manager = risk_manager
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

    # ── Portfolio & Orders ────────────────────────────────────────────

    @app.get("/api/portfolio")
    async def get_portfolio() -> JSONResponse:
        ea = app.state.exec_adapter
        if not ea:
            return JSONResponse({"positions": [], "account": {}})
        positions = await ea.get_positions()
        account = await ea.get_account()
        return JSONResponse({
            "positions": [p.model_dump(mode="json") if hasattr(p, "model_dump") else p for p in positions],
            "account": account,
        })

    @app.get("/api/orders")
    async def get_orders() -> JSONResponse:
        ea = app.state.exec_adapter
        if not ea:
            return JSONResponse({"orders": []})
        tracked = getattr(ea, "_tracked_orders", {})
        orders = []
        for oid in list(tracked):
            orders.append({"order_id": oid, "status": "tracked"})
        return JSONResponse({"orders": orders})

    @app.post("/api/orders/{order_id}/cancel")
    async def cancel_order(order_id: str) -> JSONResponse:
        ea = app.state.exec_adapter
        if not ea:
            return JSONResponse({"error": "no exec adapter"}, status_code=503)
        try:
            await ea.cancel_order(order_id)
            return JSONResponse({"status": "cancel_requested", "order_id": order_id})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    # ── Strategies ────────────────────────────────────────────────────

    @app.get("/api/strategies")
    async def get_strategies() -> JSONResponse:
        sm = app.state.strategy_manager
        if not sm:
            return JSONResponse({"strategies": []})
        return JSONResponse({"strategies": sm.get_strategy_info()})

    @app.post("/api/strategies/{strategy_id}/start")
    async def start_strategy(strategy_id: str) -> JSONResponse:
        sm = app.state.strategy_manager
        if not sm:
            return JSONResponse({"error": "no strategy manager"}, status_code=503)
        await sm.start_strategy(strategy_id)
        return JSONResponse({"status": "started", "strategy_id": strategy_id})

    @app.post("/api/strategies/{strategy_id}/stop")
    async def stop_strategy(strategy_id: str) -> JSONResponse:
        sm = app.state.strategy_manager
        if not sm:
            return JSONResponse({"error": "no strategy manager"}, status_code=503)
        await sm.stop_strategy(strategy_id)
        return JSONResponse({"status": "stopped", "strategy_id": strategy_id})

    # ── Risk ──────────────────────────────────────────────────────────

    @app.get("/api/risk")
    async def get_risk() -> JSONResponse:
        rm = app.state.risk_manager
        if not rm:
            return JSONResponse({"risk": {}})
        return JSONResponse({"risk": rm.get_risk_state()})

    @app.get("/api/risk/violations")
    async def get_risk_violations() -> JSONResponse:
        rm = app.state.risk_manager
        if not rm:
            return JSONResponse({"violations": []})
        return JSONResponse({"violations": rm.get_violations()})

    # ── P&L ───────────────────────────────────────────────────────────

    @app.get("/api/pnl")
    async def get_pnl() -> JSONResponse:
        rm = app.state.risk_manager
        pnl_data: dict[str, Any] = {"daily_pnl": 0.0, "cumulative_pnl": 0.0}
        if rm:
            pnl_data["daily_pnl"] = rm.state.daily_pnl
        sm = app.state.strategy_manager
        if sm:
            strategy_pnl = {}
            for info in sm.get_strategy_info():
                strategy_pnl[info["strategy_id"]] = info["pnl"]
            pnl_data["strategy_pnl"] = strategy_pnl
            pnl_data["cumulative_pnl"] = sum(strategy_pnl.values())
        return JSONResponse(pnl_data)

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
