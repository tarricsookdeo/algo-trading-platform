"""Tests for PerformanceMetrics."""

from __future__ import annotations

import time

import pytest

from trading_platform.core.metrics import PerformanceMetrics


@pytest.fixture
def pm():
    return PerformanceMetrics(window_seconds=1.0)


class TestCounters:
    def test_initial_state(self, pm):
        assert pm.messages_received == 0
        assert pm.messages_processed == 0
        assert pm.queue_drops == 0
        assert pm.dashboard_broadcasts == 0

    def test_record_received(self, pm):
        pm.record_received()
        pm.record_received(5)
        assert pm.messages_received == 6

    def test_record_processed(self, pm):
        pm.record_processed()
        pm.record_processed(3)
        assert pm.messages_processed == 4

    def test_record_broadcast(self, pm):
        pm.record_broadcast()
        pm.record_broadcast(2)
        assert pm.dashboard_broadcasts == 3

    def test_record_drop(self, pm):
        pm.record_drop()
        pm.record_drop(10)
        assert pm.queue_drops == 11


class TestRates:
    def test_ingestion_rate(self, pm):
        for _ in range(100):
            pm.record_received()
        rate = pm.ingestion_rate
        assert rate > 0

    def test_processing_rate(self, pm):
        for _ in range(50):
            pm.record_processed()
        rate = pm.processing_rate
        assert rate > 0

    def test_broadcast_rate(self, pm):
        for _ in range(20):
            pm.record_broadcast()
        rate = pm.broadcast_rate
        assert rate > 0

    def test_rate_zero_with_no_data(self, pm):
        assert pm.ingestion_rate == 0.0
        assert pm.processing_rate == 0.0
        assert pm.broadcast_rate == 0.0


class TestLatency:
    def test_record_latency(self, pm):
        pm.record_latency(1.5)
        pm.record_latency(2.5)
        assert pm.avg_latency_ms == 2.0
        assert pm.max_latency_ms == 2.5

    def test_latency_empty(self, pm):
        assert pm.avg_latency_ms == 0.0
        assert pm.max_latency_ms == 0.0

    def test_latency_cap(self):
        pm = PerformanceMetrics()
        for i in range(1500):
            pm.record_latency(float(i))
        # Should only keep last 1000
        assert len(pm._latency_samples) == 1000


class TestSnapshot:
    def test_snapshot_contains_all_fields(self, pm):
        pm.record_received(10)
        pm.record_processed(5)
        pm.record_broadcast(2)
        pm.record_drop(1)
        pm.record_latency(3.0)
        pm.queue_depth = 42

        snap = pm.snapshot()
        assert snap["messages_received"] == 10
        assert snap["messages_processed"] == 5
        assert snap["queue_depth"] == 42
        assert snap["queue_drops"] == 1
        assert snap["avg_latency_ms"] == 3.0
        assert snap["max_latency_ms"] == 3.0
        assert snap["dashboard_broadcasts"] == 2
        assert "ingestion_rate" in snap
        assert "processing_rate" in snap
        assert "dashboard_broadcast_rate" in snap

    def test_snapshot_is_json_serializable(self, pm):
        import json
        snap = pm.snapshot()
        json.dumps(snap)  # Should not raise
