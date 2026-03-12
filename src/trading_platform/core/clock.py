"""System clock for consistent time across components."""

import time
from datetime import UTC, datetime


def now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


def now_ns() -> int:
    """Return current time as nanosecond timestamp."""
    return time.time_ns()
