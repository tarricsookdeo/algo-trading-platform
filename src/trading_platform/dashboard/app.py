"""FastAPI dashboard application.

Serves the static HTML dashboard and exposes REST + WebSocket endpoints
for real-time monitoring and data ingestion.
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
    data_manager: Any = None,
    exec_adapter: Any = None,
    strategy_manager: Any = None,
    risk_manager: Any = None,
    bracket_manager: Any = None,
    trailing_stop_manager: Any = None,
    scaled_order_manager: Any = None,
    greeks_provider: Any = None,
    expiration_manager: Any = None,
) -> tuple[FastAPI, DashboardWSManager]:
    """Create and configure the FastAPI application.

    Returns the app and the WS manager so the platform can start/stop them.
    """
    app = FastAPI(title="Algo Trading Platform", docs_url=None, redoc_url=None)
    ws_manager = DashboardWSManager(event_bus)
    log = get_logger("dashboard.app")

    # Store references for endpoint handlers
    app.state.data_manager = data_manager
    app.state.exec_adapter = exec_adapter
    app.state.strategy_manager = strategy_manager
    app.state.risk_manager = risk_manager
    app.state.ws_manager = ws_manager
    app.state.event_bus = event_bus
    app.state.bracket_manager = bracket_manager
    app.state.trailing_stop_manager = trailing_stop_manager
    app.state.scaled_order_manager = scaled_order_manager
    app.state.greeks_provider = greeks_provider
    app.state.expiration_manager = expiration_manager

    # Mount data ingestion routes if data_manager is provided
    if data_manager is not None:
        from trading_platform.data.ingestion_server import mount_ingestion_routes
        mount_ingestion_routes(app, data_manager)

    # ── Static ────────────────────────────────────────────────────────

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    # ── REST Endpoints ────────────────────────────────────────────────

    @app.get("/api/status")
    async def status() -> JSONResponse:
        bus = app.state.event_bus
        dm = app.state.data_manager
        data: dict[str, Any] = {
            "status": "running",
            "total_events": bus.total_published,
            "events_per_second": round(bus.events_per_second(), 1),
            "subscribers": bus.subscriber_count,
        }
        if dm:
            data["data_providers"] = dm.get_provider_status()
            data["ingestion"] = dm.get_ingestion_stats()
        return JSONResponse(data)

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

    # ── Bracket Orders ────────────────────────────────────────────────

    @app.get("/api/brackets")
    async def get_brackets() -> JSONResponse:
        bm = app.state.bracket_manager
        if not bm:
            return JSONResponse({"brackets": []})
        brackets = bm.get_all_brackets()
        result = []
        for b in brackets:
            d = b.model_dump(mode="json") if hasattr(b, "model_dump") else {"bracket_id": str(b)}
            result.append(d)
        return JSONResponse({"brackets": result})

    @app.post("/api/brackets/{bracket_id}/cancel")
    async def cancel_bracket(bracket_id: str) -> JSONResponse:
        bm = app.state.bracket_manager
        if not bm:
            return JSONResponse({"error": "no bracket manager"}, status_code=503)
        try:
            ok = await bm.cancel_bracket(bracket_id)
            return JSONResponse({"status": "cancel_requested" if ok else "not_found", "bracket_id": bracket_id})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    # ── Trailing Stops ────────────────────────────────────────────────

    @app.get("/api/trailing-stops")
    async def get_trailing_stops() -> JSONResponse:
        tsm = app.state.trailing_stop_manager
        if not tsm:
            return JSONResponse({"trailing_stops": []})
        active = tsm.get_active_trailing_stops()
        result = []
        for ts in active:
            result.append({
                "trailing_stop_id": ts.trailing_stop_id,
                "symbol": ts.symbol,
                "quantity": str(ts.quantity),
                "trail_amount": str(ts.trail_amount) if ts.trail_amount else None,
                "trail_percent": str(ts.trail_percent) if ts.trail_percent else None,
                "current_stop_price": str(ts.current_stop_price),
                "highest_price": str(ts.highest_price),
                "state": ts.state,
                "stop_order_id": ts.stop_order_id,
            })
        return JSONResponse({"trailing_stops": result})

    # ── Scaled Orders ─────────────────────────────────────────────────

    @app.get("/api/scaled-orders")
    async def get_scaled_orders() -> JSONResponse:
        som = app.state.scaled_order_manager
        if not som:
            return JSONResponse({"scaled_exits": [], "scaled_entries": []})
        exits = []
        for se in getattr(som, "_exits", {}).values():
            tranches = []
            for t in se.tranches:
                tranches.append({
                    "price": str(t.price),
                    "quantity": str(t.quantity),
                    "filled": t.filled,
                    "order_id": t.order_id,
                })
            exits.append({
                "scaled_id": se.scaled_id,
                "symbol": se.symbol,
                "total_quantity": str(se.total_quantity),
                "remaining_quantity": str(se.remaining_quantity),
                "stop_loss_price": str(se.stop_loss_price),
                "state": se.state,
                "tranches": tranches,
            })
        entries = []
        for en in getattr(som, "_entries", {}).values():
            tranches = []
            for t in en.tranches:
                tranches.append({
                    "price": str(t.price),
                    "quantity": str(t.quantity),
                    "filled": t.filled,
                    "order_id": t.order_id,
                })
            entries.append({
                "scaled_id": en.scaled_id,
                "symbol": en.symbol,
                "total_quantity": str(en.total_quantity),
                "filled_quantity": str(en.filled_quantity),
                "stop_loss_price": str(en.stop_loss_price),
                "state": en.state,
                "tranches": tranches,
            })
        return JSONResponse({"scaled_exits": exits, "scaled_entries": entries})

    # ── Greeks ────────────────────────────────────────────────────────

    @app.get("/api/greeks")
    async def get_greeks() -> JSONResponse:
        gp = app.state.greeks_provider
        ea = app.state.exec_adapter
        if not gp:
            return JSONResponse({"portfolio_greeks": {}, "positions": []})
        positions = []
        if ea:
            if hasattr(ea, "get_option_positions"):
                positions = await ea.get_option_positions()
            else:
                positions = await ea.get_positions()
        agg = await gp.get_portfolio_greeks(positions)
        return JSONResponse({
            "portfolio_greeks": {
                "total_delta": agg.total_delta,
                "total_gamma": agg.total_gamma,
                "total_theta": agg.total_theta,
                "total_vega": agg.total_vega,
                "position_count": agg.position_count,
            },
            "positions": [
                p.model_dump(mode="json") if hasattr(p, "model_dump") else p
                for p in positions
            ],
        })

    # ── Expiration Manager ────────────────────────────────────────────

    @app.get("/api/expirations")
    async def get_expirations() -> JSONResponse:
        em = app.state.expiration_manager
        if not em:
            return JSONResponse({"positions": []})
        result = []
        for pos in getattr(em, "_positions", []):
            from datetime import date
            today = date.today()
            dte = (pos.expiration_date - today).days
            result.append({
                "symbol": pos.symbol,
                "underlying": pos.underlying,
                "quantity": pos.quantity,
                "contract_type": pos.contract_type.value if hasattr(pos.contract_type, "value") else str(pos.contract_type),
                "strike_price": pos.strike_price,
                "expiration_date": pos.expiration_date.isoformat(),
                "dte": dte,
                "strategy_type": pos.strategy_type,
            })
        return JSONResponse({"positions": result})

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
