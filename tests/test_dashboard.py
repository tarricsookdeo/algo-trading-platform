"""Tests for dashboard endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from trading_platform.core.events import EventBus
from trading_platform.dashboard.app import create_app
from trading_platform.data.manager import DataManager
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_data_manager(bus):
    dm = DataManager(bus)
    dm.bars_received = 500
    dm.quotes_received = 1000
    dm.trades_received = 200
    return dm


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
def client(bus, mock_data_manager, mock_exec, mock_strategy_manager, risk_manager):
    app, _ = create_app(
        bus,
        data_manager=mock_data_manager,
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
        assert "data_providers" in data
        assert "ingestion" in data
        assert data["ingestion"]["bars_received"] == 500

    def test_status_without_data_manager(self, bus):
        app, _ = create_app(bus)
        c = TestClient(app)
        resp = c.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "data_providers" not in data


# ── Portfolio ─────────────────────────────────────────────────────────


class TestPortfolio:
    def test_get_portfolio(self, client, mock_exec):
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert data["account"]["equity"] == 100000

    def test_get_portfolio_no_exec(self, bus, mock_data_manager):
        app, _ = create_app(bus, data_manager=mock_data_manager)
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

    def test_cancel_order_no_exec(self, bus, mock_data_manager):
        app, _ = create_app(bus, data_manager=mock_data_manager)
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

    def test_strategies_no_manager(self, bus, mock_data_manager):
        app, _ = create_app(bus, data_manager=mock_data_manager)
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

    def test_risk_no_manager(self, bus, mock_data_manager):
        app, _ = create_app(bus, data_manager=mock_data_manager)
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

    def test_pnl_no_managers(self, bus, mock_data_manager):
        app, _ = create_app(bus, data_manager=mock_data_manager)
        c = TestClient(app)
        resp = c.get("/api/pnl")
        data = resp.json()
        assert data["daily_pnl"] == 0.0
        assert data["cumulative_pnl"] == 0.0


# ── Data Ingestion Endpoints ──────────────────────────────────────────


class TestDataIngestion:
    def test_ingest_bar(self, client, mock_data_manager):
        bar_data = {
            "symbol": "AAPL",
            "open": 185.0,
            "high": 186.0,
            "low": 184.5,
            "close": 185.5,
            "volume": 10000,
            "timestamp": "2024-01-15T09:30:00",
        }
        resp = client.post("/api/data/bars", json=bar_data)
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1

    def test_ingest_bars_batch(self, client, mock_data_manager):
        bars = [
            {
                "symbol": "AAPL",
                "open": 185.0,
                "high": 186.0,
                "low": 184.5,
                "close": 185.5,
                "volume": 10000,
                "timestamp": "2024-01-15T09:30:00",
            },
            {
                "symbol": "MSFT",
                "open": 380.0,
                "high": 381.0,
                "low": 379.0,
                "close": 380.5,
                "volume": 5000,
                "timestamp": "2024-01-15T09:30:00",
            },
        ]
        resp = client.post("/api/data/bars", json=bars)
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 2

    def test_ingest_quote(self, client, mock_data_manager):
        quote_data = {
            "symbol": "AAPL",
            "bid_price": 185.0,
            "bid_size": 100,
            "ask_price": 185.5,
            "ask_size": 200,
            "timestamp": "2024-01-15T09:30:00",
        }
        resp = client.post("/api/data/quotes", json=quote_data)
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1

    def test_ingest_trade(self, client, mock_data_manager):
        trade_data = {
            "symbol": "AAPL",
            "price": 185.25,
            "size": 100,
            "timestamp": "2024-01-15T09:30:00",
        }
        resp = client.post("/api/data/trades", json=trade_data)
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1

    def test_data_status(self, client):
        resp = client.get("/api/data/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "bars_received" in data
        assert "quotes_received" in data
        assert "trades_received" in data

    def test_data_providers(self, client):
        resp = client.get("/api/data/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
