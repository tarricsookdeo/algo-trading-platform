"""Parse Alpaca WebSocket / REST messages into domain models.

Handles both stock (JSON) and option (msgpack-decoded dict) message formats.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_platform.core.enums import BarType
from trading_platform.core.models import Bar, LULD, QuoteTick, TradeTick, TradingStatus


def _parse_ts(raw: str | None) -> datetime:
    """Parse an RFC-3339 timestamp string to a UTC datetime."""
    if not raw:
        return datetime.now(UTC)
    s = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


# ── Stock parsers (JSON messages) ─────────────────────────────────────


def parse_stock_trade(msg: dict) -> TradeTick:
    return TradeTick(
        symbol=msg["S"],
        price=float(msg["p"]),
        size=float(msg["s"]),
        exchange=msg.get("x", ""),
        trade_id=str(msg.get("i", "")),
        conditions=msg.get("c") or [],
        timestamp=_parse_ts(msg.get("t")),
        tape=msg.get("z", ""),
    )


def parse_stock_quote(msg: dict) -> QuoteTick:
    return QuoteTick(
        symbol=msg["S"],
        bid_price=float(msg.get("bp", 0)),
        bid_size=float(msg.get("bs", 0)),
        ask_price=float(msg.get("ap", 0)),
        ask_size=float(msg.get("as", 0)),
        bid_exchange=msg.get("bx", ""),
        ask_exchange=msg.get("ax", ""),
        timestamp=_parse_ts(msg.get("t")),
        conditions=msg.get("c") or [],
    )


def parse_stock_bar(msg: dict) -> Bar:
    type_map = {"b": BarType.MINUTE, "d": BarType.DAILY, "u": BarType.UPDATED}
    return Bar(
        symbol=msg["S"],
        open=float(msg["o"]),
        high=float(msg["h"]),
        low=float(msg["l"]),
        close=float(msg["c"]),
        volume=float(msg["v"]),
        vwap=float(msg.get("vw", 0)),
        trade_count=int(msg.get("n", 0)),
        timestamp=_parse_ts(msg.get("t")),
        bar_type=type_map.get(msg.get("T", "b"), BarType.MINUTE),
    )


def parse_trading_status(msg: dict) -> TradingStatus:
    return TradingStatus(
        symbol=msg["S"],
        status_code=msg.get("sc", ""),
        status_message=msg.get("sm", ""),
        reason_code=msg.get("rc", ""),
        reason_message=msg.get("rm", ""),
        timestamp=_parse_ts(msg.get("t")),
    )


def parse_luld(msg: dict) -> LULD:
    return LULD(
        symbol=msg["S"],
        limit_up=float(msg.get("u", 0)),
        limit_down=float(msg.get("d", 0)),
        indicator=msg.get("i", ""),
        timestamp=_parse_ts(msg.get("t")),
    )


# ── Option parsers (msgpack-decoded dicts) ────────────────────────────


def parse_option_trade(msg: dict) -> TradeTick:
    cond = msg.get("c")
    conditions = [cond] if isinstance(cond, str) else (cond or [])
    return TradeTick(
        symbol=msg["S"],
        price=float(msg["p"]),
        size=float(msg["s"]),
        exchange=msg.get("x", ""),
        trade_id="",
        conditions=conditions,
        timestamp=_parse_ts(msg.get("t")),
    )


def parse_option_quote(msg: dict) -> QuoteTick:
    cond = msg.get("c")
    conditions = [cond] if isinstance(cond, str) else (cond or [])
    return QuoteTick(
        symbol=msg["S"],
        bid_price=float(msg.get("bp", 0)),
        bid_size=float(msg.get("bs", 0)),
        ask_price=float(msg.get("ap", 0)),
        ask_size=float(msg.get("as", 0)),
        bid_exchange=msg.get("bx", ""),
        ask_exchange=msg.get("ax", ""),
        timestamp=_parse_ts(msg.get("t")),
        conditions=conditions,
    )
