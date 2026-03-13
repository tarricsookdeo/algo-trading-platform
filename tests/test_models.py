"""Tests for domain models."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from trading_platform.core.enums import AssetClass, BarType, OrderSide, OrderType
from trading_platform.core.models import (
    Bar,
    Fill,
    Instrument,
    LULD,
    Order,
    Position,
    QuoteTick,
    SystemEvent,
    TradeTick,
    TradingStatus,
)


def test_quote_tick_creation():
    q = QuoteTick(
        symbol="AAPL",
        bid_price=150.00,
        bid_size=100,
        ask_price=150.05,
        ask_size=200,
        bid_exchange="Q",
        ask_exchange="P",
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        conditions=["R"],
    )
    assert q.symbol == "AAPL"
    assert q.bid_price == 150.00
    assert q.ask_price == 150.05


def test_quote_tick_json_serializable():
    q = QuoteTick(
        symbol="MSFT",
        bid_price=400.0,
        bid_size=50,
        ask_price=400.10,
        ask_size=75,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )
    data = q.model_dump(mode="json")
    text = json.dumps(data)
    assert "MSFT" in text
    assert "400.0" in text


def test_trade_tick_creation():
    t = TradeTick(
        symbol="TSLA",
        price=250.50,
        size=10,
        exchange="V",
        trade_id="12345",
        conditions=["@", "T"],
        timestamp=datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC),
        tape="C",
    )
    assert t.symbol == "TSLA"
    assert t.price == 250.50
    assert t.tape == "C"


def test_bar_creation():
    b = Bar(
        symbol="GOOGL",
        open=140.0,
        high=142.5,
        low=139.0,
        close=141.75,
        volume=1_000_000,
        vwap=141.2,
        trade_count=5000,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        bar_type=BarType.MINUTE,
    )
    assert b.symbol == "GOOGL"
    assert b.bar_type == BarType.MINUTE
    assert b.volume == 1_000_000


def test_trading_status():
    s = TradingStatus(
        symbol="AAPL",
        status_code="T",
        status_message="Trading",
        timestamp=datetime.now(UTC),
    )
    assert s.status_code == "T"


def test_luld():
    l = LULD(
        symbol="AAPL",
        limit_up=155.0,
        limit_down=145.0,
        indicator="B",
        timestamp=datetime.now(UTC),
    )
    assert l.limit_up == 155.0
    assert l.limit_down == 145.0


def test_instrument():
    i = Instrument(
        symbol="AAPL",
        name="Apple Inc.",
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        tradable=True,
    )
    assert i.asset_class == AssetClass.EQUITY
    assert i.tradable is True
    assert i.strike is None


def test_instrument_option():
    i = Instrument(
        symbol="AAPL250321P00200000",
        name="AAPL Put",
        asset_class=AssetClass.OPTION,
        strike=200.0,
        expiry=datetime(2025, 3, 21, tzinfo=UTC),
        option_type="put",
        underlying="AAPL",
    )
    assert i.asset_class == AssetClass.OPTION
    assert i.strike == 200.0
    assert i.underlying == "AAPL"


def test_order_defaults():
    o = Order()
    assert o.side == OrderSide.BUY
    assert o.order_type == OrderType.MARKET


def test_fill_defaults():
    f = Fill()
    assert f.price == 0.0


def test_position_defaults():
    p = Position()
    assert p.quantity == Decimal("0")


def test_system_event():
    e = SystemEvent(component="test", message="hello", level="info")
    assert e.component == "test"
