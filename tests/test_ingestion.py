"""Tests for REST and WebSocket data ingestion endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from trading_platform.core.events import EventBus
from trading_platform.dashboard.app import create_app
from trading_platform.data.config import DataConfig
from trading_platform.data.manager import DataManager


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def data_manager(bus):
    cfg = DataConfig(max_bars_per_request=5)
    return DataManager(bus, config=cfg)


@pytest.fixture
def client(bus, data_manager):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        app, _ = loop.run_until_complete(create_app(bus, data_manager=data_manager))
    finally:
        loop.close()
    return TestClient(app)


class TestBarIngestion:
    def test_ingest_single_bar(self, client, data_manager):
        resp = client.post("/api/data/bars", json={
            "symbol": "AAPL",
            "open": 185.0,
            "high": 186.0,
            "low": 184.5,
            "close": 185.5,
            "volume": 10000,
            "timestamp": "2024-01-15T09:30:00",
        })
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1
        assert data_manager.bars_received == 1

    def test_ingest_bar_batch(self, client, data_manager):
        bars = [
            {
                "symbol": "AAPL",
                "open": 185.0, "high": 186.0, "low": 184.5, "close": 185.5,
                "volume": 10000, "timestamp": "2024-01-15T09:30:00",
            },
            {
                "symbol": "MSFT",
                "open": 380.0, "high": 381.0, "low": 379.0, "close": 380.5,
                "volume": 5000, "timestamp": "2024-01-15T09:30:00",
            },
        ]
        resp = client.post("/api/data/bars", json=bars)
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 2
        assert data_manager.bars_received == 2

    def test_ingest_bar_exceeds_limit(self, client):
        bars = [
            {
                "symbol": f"SYM{i}",
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 1000, "timestamp": "2024-01-15T09:30:00",
            }
            for i in range(6)
        ]
        resp = client.post("/api/data/bars", json=bars)
        assert resp.status_code == 400
        assert "max" in resp.json()["error"]

    def test_ingest_invalid_bar(self, client, data_manager):
        resp = client.post("/api/data/bars", json={"bad": "data"})
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 0


class TestQuoteIngestion:
    def test_ingest_single_quote(self, client, data_manager):
        resp = client.post("/api/data/quotes", json={
            "symbol": "AAPL",
            "bid_price": 185.0,
            "bid_size": 100,
            "ask_price": 185.5,
            "ask_size": 200,
            "timestamp": "2024-01-15T09:30:00",
        })
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1
        assert data_manager.quotes_received == 1


class TestTradeIngestion:
    def test_ingest_single_trade(self, client, data_manager):
        resp = client.post("/api/data/trades", json={
            "symbol": "AAPL",
            "price": 185.25,
            "size": 100,
            "timestamp": "2024-01-15T09:30:00",
        })
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 1
        assert data_manager.trades_received == 1


class TestDataStatusEndpoints:
    def test_data_status(self, client):
        resp = client.get("/api/data/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bars_received"] == 0
        assert data["providers"] == 0

    def test_data_providers(self, client):
        resp = client.get("/api/data/providers")
        assert resp.status_code == 200
        assert resp.json()["providers"] == []


class TestWebSocketIngestion:
    def test_ws_ingest_bar(self, client, data_manager):
        # Single-message ingestion uses fire-and-forget (no ack on success)
        with client.websocket_connect("/ws/data") as ws:
            ws.send_text(json.dumps({
                "type": "bar",
                "data": {
                    "symbol": "AAPL",
                    "open": 185.0, "high": 186.0, "low": 184.5, "close": 185.5,
                    "volume": 10000, "timestamp": "2024-01-15T09:30:00",
                },
            }))
        assert data_manager.bars_received == 1

    def test_ws_ingest_unknown_type(self, client):
        with client.websocket_connect("/ws/data") as ws:
            ws.send_text(json.dumps({"type": "unknown", "data": {}}))
            resp = ws.receive_json()
            assert "error" in resp

    def test_ws_ingest_invalid_json(self, client):
        with client.websocket_connect("/ws/data") as ws:
            ws.send_text("not json")
            resp = ws.receive_json()
            assert "error" in resp
