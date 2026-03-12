"""Tests for Phase 7: Dashboard endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from trading_platform.core.events import EventBus
from trading_platform.dashboard.app import create_app
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_adapter():
    adp = MagicMock()
    adp.stock_stream = MagicMock()
    adp.stock_stream.is_connected = True
    adp.stock_stream.messages_received = 1000
    adp.stock_stream.reconnect_count = 0
    adp.stock_stream._trade_symbols = {"AAPL", "MSFT"}
    adp.stock_stream._quote_symbols = {"AAPL", "MSFT"}
    adp.options_stream = MagicMock()
    adp.options_stream.is_connected = True
    adp.options_stream.messages_received = 500
    adp.options_stream.reconnect_count = 0
    adp.subscribe_trades = AsyncMock()
    adp.subscribe_quotes = AsyncMock()
    adp.subscribe_bars = AsyncMock()
    adp.unsubscribe = AsyncMock()
    return adp


@pytest.fixture
def mock_exec():
    ea = AsyncMock()
    ea.get_positions = AsyncMock(return_value=[])
    ea.get_account = AsyncMock(return_value={"equity": 100000})
    ea._tracked_orders = {"order-1": {}}
    ea.cancel_order = AsyncMock()
    return ea


@pytest.fixture
def mock_strategy_manager():
    sm = MagicMock()
    sm.get_strategy_info = MagicMock(return_value=[
        {
            "strategy_id": "sma_cross",
            "state": "active",
            "trades_executed": 5,
            "win_rate": 0.6,
            "pnl": 250.0,
            "signals": 10,
        }
    ])
    sm.start_strategy = AsyncMock()
    sm.stop_strategy = AsyncMock()
    return sm


@pytest.fixture
def risk_manager(bus):
    config = RiskConfig()
    rm = RiskManager(config, bus)
    rm.state.daily_pnl = -1500.0
    rm.state.daily_trade_count = 25
    return rm


@pytest.fixture
def client(bus, mock_adapter, mock_exec, mock_strategy_manager, risk_manager):
    app, _ = create_app(
        bus,
        adapter=mock_adapter,
        exec_adapter=mock_exec,
        strategy_manager=mock_strategy_manager,
        risk_manager=risk_manager,
    )
    return TestClient(app)


# ── Index ─────────────────────────────────────────────────────────────


class TestIndex:
    def test_serves_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


# ── Status ────────────────────────────────────────────────────────────


class TestStatus:
    def test_returns_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "total_events" in data
        assert "stock_stream" in data
        assert data["stock_stream"]["connected"] is True


# ── Subscriptions ─────────────────────────────────────────────────────


class TestSubscriptions:
    def test_get_subscriptions(self, client):
        resp = client.get("/api/subscriptions")
        assert resp.status_code == 200
        data = resp.json()
        assert "AAPL" in data["symbols"]

    def test_subscribe(self, client, mock_adapter):
        resp = client.post("/api/subscribe", json={"symbol": "TSLA"})
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "TSLA"
        mock_adapter.subscribe_trades.assert_awaited()

    def test_subscribe_empty_symbol(self, client):
        resp = client.post("/api/subscribe", json={"symbol": ""})
        assert resp.status_code == 400

    def test_unsubscribe(self, client, mock_adapter):
        resp = client.delete("/api/subscribe/AAPL")
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "AAPL"
        mock_adapter.unsubscribe.assert_awaited()


# ── Portfolio ─────────────────────────────────────────────────────────


class TestPortfolio:
    def test_get_portfolio(self, client, mock_exec):
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert data["account"]["equity"] == 100000

    def test_get_portfolio_no_exec(self, bus, mock_adapter):
        app, _ = create_app(bus, adapter=mock_adapter)
        c = TestClient(app)
        resp = c.get("/api/portfolio")
        assert resp.status_code == 200
        assert resp.json()["positions"] == []


# ── Orders ────────────────────────────────────────────────────────────


class TestOrders:
    def test_get_orders(self, client):
        resp = client.get("/api/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["orders"]) == 1
        assert data["orders"][0]["order_id"] == "order-1"

    def test_cancel_order(self, client, mock_exec):
        resp = client.post("/api/orders/order-1/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancel_requested"
        mock_exec.cancel_order.assert_awaited_once_with("order-1")

    def test_cancel_order_no_exec(self, bus, mock_adapter):
        app, _ = create_app(bus, adapter=mock_adapter)
        c = TestClient(app)
        resp = c.post("/api/orders/order-1/cancel")
        assert resp.status_code == 503


# ── Strategies ────────────────────────────────────────────────────────


class TestStrategies:
    def test_get_strategies(self, client):
        resp = client.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["strategies"]) == 1
        assert data["strategies"][0]["strategy_id"] == "sma_cross"
        assert data["strategies"][0]["state"] == "active"

    def test_start_strategy(self, client, mock_strategy_manager):
        resp = client.post("/api/strategies/sma_cross/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"
        mock_strategy_manager.start_strategy.assert_awaited_once_with("sma_cross")

    def test_stop_strategy(self, client, mock_strategy_manager):
        resp = client.post("/api/strategies/sma_cross/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"
        mock_strategy_manager.stop_strategy.assert_awaited_once_with("sma_cross")

    def test_strategies_no_manager(self, bus, mock_adapter):
        app, _ = create_app(bus, adapter=mock_adapter)
        c = TestClient(app)
        resp = c.get("/api/strategies")
        assert resp.json()["strategies"] == []


# ── Risk ──────────────────────────────────────────────────────────────


class TestRisk:
    def test_get_risk(self, client):
        resp = client.get("/api/risk")
        assert resp.status_code == 200
        data = resp.json()["risk"]
        assert data["daily_pnl"] == -1500.0
        assert data["daily_trade_count"] == 25
        assert data["is_halted"] is False

    def test_get_risk_violations(self, client):
        resp = client.get("/api/risk/violations")
        assert resp.status_code == 200
        assert "violations" in resp.json()

    def test_risk_no_manager(self, bus, mock_adapter):
        app, _ = create_app(bus, adapter=mock_adapter)
        c = TestClient(app)
        resp = c.get("/api/risk")
        assert resp.json()["risk"] == {}


# ── P&L ───────────────────────────────────────────────────────────────


class TestPnl:
    def test_get_pnl(self, client):
        resp = client.get("/api/pnl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_pnl"] == -1500.0
        assert "strategy_pnl" in data
        assert data["strategy_pnl"]["sma_cross"] == 250.0
        assert data["cumulative_pnl"] == 250.0

    def test_pnl_no_managers(self, bus, mock_adapter):
        app, _ = create_app(bus, adapter=mock_adapter)
        c = TestClient(app)
        resp = c.get("/api/pnl")
        data = resp.json()
        assert data["daily_pnl"] == 0.0
        assert data["cumulative_pnl"] == 0.0
