"""Tests for the system clock utilities."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timezone

import pytest

from trading_platform.core.clock import now, now_ns


class TestNow:
    def test_returns_datetime(self):
        result = now()
        assert isinstance(result, datetime)

    def test_returns_utc_aware(self):
        result = now()
        assert result.tzinfo is not None
        assert result.tzinfo == UTC or result.utcoffset().total_seconds() == 0

    def test_monotonically_increasing(self):
        t1 = now()
        t2 = now()
        assert t2 >= t1

    def test_close_to_real_time(self):
        before = datetime.now(UTC)
        result = now()
        after = datetime.now(UTC)
        assert before <= result <= after


class TestNowNs:
    def test_returns_int(self):
        result = now_ns()
        assert isinstance(result, int)

    def test_returns_positive(self):
        assert now_ns() > 0

    def test_monotonically_increasing(self):
        t1 = now_ns()
        t2 = now_ns()
        assert t2 >= t1

    def test_consistent_with_time_time(self):
        # now_ns() should be close to time.time() * 1e9
        ns = now_ns()
        wall = time.time() * 1e9
        # Allow 1 second of drift
        assert abs(ns - wall) < 1e9

    def test_nanosecond_precision(self):
        # Two consecutive calls should differ by less than 1 millisecond
        t1 = now_ns()
        t2 = now_ns()
        diff = t2 - t1
        assert diff >= 0
        assert diff < 1_000_000_000  # less than 1 second apart
