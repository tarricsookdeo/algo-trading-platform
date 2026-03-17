"""Tests for batch REST and WebSocket ingestion endpoints."""

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
    cfg = DataConfig(max_bars_per_request=10)
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


class TestBatchBarEndpoint:
    def test_ingest_bars_batch(self, client, data_manager):
        bars = [
            {
                "symbol": f"SYM{i}",
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 1000, "timestamp": "2024-01-15T09:30:00",
            }
            for i in range(5)
        ]
        resp = client.post("/api/data/bars/batch", json=bars)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested"] == 5
        assert data["errors"] == 0
        assert data_manager.bars_received == 5

    def test_batch_bars_exceeds_limit(self, client):
        bars = [
            {
                "symbol": f"SYM{i}",
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 1000, "timestamp": "2024-01-15T09:30:00",
            }
            for i in range(11)
        ]
        resp = client.post("/api/data/bars/batch", json=bars)
        assert resp.status_code == 400
        assert "max" in resp.json()["error"]

    def test_batch_bars_with_errors(self, client, data_manager):
        bars = [
            {
                "symbol": "AAPL",
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 1000, "timestamp": "2024-01-15T09:30:00",
            },
            {"bad": "data"},
        ]
        resp = client.post("/api/data/bars/batch", json=bars)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested"] == 1
        assert data["errors"] == 1


class TestBatchQuoteEndpoint:
    def test_ingest_quotes_batch(self, client, data_manager):
        quotes = [
            {
                "symbol": f"SYM{i}",
                "bid_price": 100.0, "bid_size": 100,
                "ask_price": 100.5, "ask_size": 200,
                "timestamp": "2024-01-15T09:30:00",
            }
            for i in range(3)
        ]
        resp = client.post("/api/data/quotes/batch", json=quotes)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested"] == 3
        assert data["errors"] == 0
        assert data_manager.quotes_received == 3

    def test_batch_quotes_with_errors(self, client, data_manager):
        quotes = [
            {
                "symbol": "AAPL",
                "bid_price": 100.0, "bid_size": 100,
                "ask_price": 100.5, "ask_size": 200,
                "timestamp": "2024-01-15T09:30:00",
            },
            {"invalid": "data"},
        ]
        resp = client.post("/api/data/quotes/batch", json=quotes)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested"] == 1
        assert data["errors"] == 1


class TestBatchTradeEndpoint:
    def test_ingest_trades_batch(self, client, data_manager):
        trades = [
            {
                "symbol": f"SYM{i}",
                "price": 100.0 + i, "size": 100,
                "timestamp": "2024-01-15T09:30:00",
            }
            for i in range(4)
        ]
        resp = client.post("/api/data/trades/batch", json=trades)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested"] == 4
        assert data["errors"] == 0
        assert data_manager.trades_received == 4


class TestBatchWebSocket:
    def test_ws_batch_frame(self, client, data_manager):
        with client.websocket_connect("/ws/data") as ws:
            batch = [
                {
                    "type": "bar",
                    "data": {
                        "symbol": "AAPL",
                        "open": 185.0, "high": 186.0, "low": 184.5, "close": 185.5,
                        "volume": 10000, "timestamp": "2024-01-15T09:30:00",
                    },
                },
                {
                    "type": "quote",
                    "data": {
                        "symbol": "MSFT",
                        "bid_price": 380.0, "bid_size": 100,
                        "ask_price": 380.5, "ask_size": 200,
                        "timestamp": "2024-01-15T09:30:00",
                    },
                },
            ]
            ws.send_text(json.dumps(batch))
            resp = ws.receive_json()
            assert resp["status"] == "ok"
            assert resp["batch"] is True
            assert len(resp["results"]) == 2
            assert all(r["status"] == "ok" for r in resp["results"])

        assert data_manager.bars_received == 1
        assert data_manager.quotes_received == 1

    def test_ws_batch_with_error(self, client, data_manager):
        with client.websocket_connect("/ws/data") as ws:
            batch = [
                {
                    "type": "trade",
                    "data": {
                        "symbol": "AAPL", "price": 185.25,
                        "size": 100, "timestamp": "2024-01-15T09:30:00",
                    },
                },
                {"type": "unknown", "data": {}},
            ]
            ws.send_text(json.dumps(batch))
            resp = ws.receive_json()
            assert resp["batch"] is True
            assert resp["results"][0]["status"] == "ok"
            assert "error" in resp["results"][1]

    def test_ws_single_still_works(self, client, data_manager):
        # Single-message ingestion uses fire-and-forget (no ack on success)
        with client.websocket_connect("/ws/data") as ws:
            ws.send_text(json.dumps({
                "type": "trade",
                "data": {
                    "symbol": "AAPL", "price": 185.25,
                    "size": 100, "timestamp": "2024-01-15T09:30:00",
                },
            }))
        assert data_manager.trades_received == 1


class TestMetricsEndpoint:
    def test_metrics_endpoint_no_perf(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "performance" in data
        assert "message_queue" in data

    def test_metrics_endpoint_with_perf(self, bus, data_manager):
        import asyncio
        from trading_platform.core.metrics import PerformanceMetrics

        pm = PerformanceMetrics()
        pm.record_received(10)
        pm.record_processed(5)

        loop = asyncio.new_event_loop()
        try:
            app, _ = loop.run_until_complete(create_app(bus, data_manager=data_manager, perf_metrics=pm))
        finally:
            loop.close()
        client = TestClient(app)

        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["performance"]["messages_received"] == 10
        assert data["performance"]["messages_processed"] == 5

    def test_metrics_endpoint_with_mq(self, bus, data_manager):
        import asyncio
        from trading_platform.core.message_queue import MessageQueue
        from trading_platform.core.metrics import PerformanceMetrics

        pm = PerformanceMetrics()
        mq = MessageQueue(max_size=100)

        loop = asyncio.new_event_loop()
        try:
            app, _ = loop.run_until_complete(create_app(
                bus, data_manager=data_manager, perf_metrics=pm, message_queue=mq
            ))
        finally:
            loop.close()
        client = TestClient(app)

        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "message_queue" in data
        assert data["message_queue"]["max_size"] == 100
