"""Tests for Alpaca message parsers."""

from trading_platform.adapters.alpaca.parse import (
    parse_luld,
    parse_option_quote,
    parse_option_trade,
    parse_stock_bar,
    parse_stock_quote,
    parse_stock_trade,
    parse_trading_status,
)
from trading_platform.core.enums import BarType


class TestStockTradeParsing:
    def test_basic_trade(self):
        msg = {
            "T": "t",
            "S": "AAPL",
            "i": 12345,
            "x": "V",
            "p": 150.25,
            "s": 100,
            "c": ["@", "T"],
            "t": "2024-01-15T14:30:00.123456789Z",
            "z": "C",
        }
        tick = parse_stock_trade(msg)
        assert tick.symbol == "AAPL"
        assert tick.price == 150.25
        assert tick.size == 100
        assert tick.exchange == "V"
        assert tick.trade_id == "12345"
        assert tick.conditions == ["@", "T"]
        assert tick.tape == "C"

    def test_trade_missing_optional_fields(self):
        msg = {"T": "t", "S": "MSFT", "p": 400.0, "s": 50, "t": "2024-01-15T10:00:00Z"}
        tick = parse_stock_trade(msg)
        assert tick.symbol == "MSFT"
        assert tick.exchange == ""
        assert tick.conditions == []


class TestStockQuoteParsing:
    def test_basic_quote(self):
        msg = {
            "T": "q",
            "S": "AAPL",
            "bx": "Q",
            "bp": 150.00,
            "bs": 200,
            "ax": "P",
            "ap": 150.05,
            "as": 100,
            "c": ["R"],
            "t": "2024-01-15T14:30:00Z",
            "z": "C",
        }
        tick = parse_stock_quote(msg)
        assert tick.symbol == "AAPL"
        assert tick.bid_price == 150.00
        assert tick.ask_price == 150.05
        assert tick.bid_exchange == "Q"
        assert tick.ask_exchange == "P"

    def test_quote_no_conditions(self):
        msg = {
            "T": "q",
            "S": "TSLA",
            "bp": 250.0,
            "bs": 10,
            "ap": 250.5,
            "as": 20,
            "t": "2024-01-15T10:00:00Z",
        }
        tick = parse_stock_quote(msg)
        assert tick.conditions == []


class TestStockBarParsing:
    def test_minute_bar(self):
        msg = {
            "T": "b",
            "S": "GOOGL",
            "o": 140.0,
            "h": 142.5,
            "l": 139.0,
            "c": 141.75,
            "v": 1000000,
            "vw": 141.2,
            "n": 5000,
            "t": "2024-01-15T10:00:00Z",
        }
        bar = parse_stock_bar(msg)
        assert bar.symbol == "GOOGL"
        assert bar.open == 140.0
        assert bar.close == 141.75
        assert bar.bar_type == BarType.MINUTE

    def test_daily_bar(self):
        msg = {
            "T": "d",
            "S": "AAPL",
            "o": 150.0,
            "h": 155.0,
            "l": 149.0,
            "c": 153.0,
            "v": 50000000,
            "t": "2024-01-15T00:00:00Z",
        }
        bar = parse_stock_bar(msg)
        assert bar.bar_type == BarType.DAILY

    def test_updated_bar(self):
        msg = {
            "T": "u",
            "S": "AAPL",
            "o": 150.0,
            "h": 155.0,
            "l": 149.0,
            "c": 154.0,
            "v": 55000000,
            "t": "2024-01-15T15:00:00Z",
        }
        bar = parse_stock_bar(msg)
        assert bar.bar_type == BarType.UPDATED


class TestTradingStatusParsing:
    def test_basic_status(self):
        msg = {
            "T": "s",
            "S": "AAPL",
            "sc": "T",
            "sm": "Trading",
            "rc": "",
            "rm": "",
            "t": "2024-01-15T09:30:00Z",
        }
        status = parse_trading_status(msg)
        assert status.symbol == "AAPL"
        assert status.status_code == "T"
        assert status.status_message == "Trading"


class TestLULDParsing:
    def test_basic_luld(self):
        msg = {
            "T": "l",
            "S": "AAPL",
            "u": 155.00,
            "d": 145.00,
            "i": "B",
            "t": "2024-01-15T10:00:00Z",
        }
        luld = parse_luld(msg)
        assert luld.symbol == "AAPL"
        assert luld.limit_up == 155.0
        assert luld.limit_down == 145.0
        assert luld.indicator == "B"


class TestOptionParsing:
    def test_option_trade(self):
        msg = {
            "T": "t",
            "S": "AAPL250321P00200000",
            "p": 5.50,
            "s": 10,
            "x": "C",
            "c": "A",
            "t": "2024-01-15T10:00:00Z",
        }
        tick = parse_option_trade(msg)
        assert tick.symbol == "AAPL250321P00200000"
        assert tick.price == 5.50
        assert tick.conditions == ["A"]

    def test_option_trade_no_condition(self):
        msg = {
            "T": "t",
            "S": "MSFT250117C00400000",
            "p": 12.0,
            "s": 5,
            "x": "B",
            "t": "2024-01-15T10:00:00Z",
        }
        tick = parse_option_trade(msg)
        assert tick.conditions == []

    def test_option_quote(self):
        msg = {
            "T": "q",
            "S": "AAPL250321P00200000",
            "bx": "C",
            "bp": 5.40,
            "bs": 50,
            "ax": "B",
            "ap": 5.60,
            "as": 30,
            "c": "A",
            "t": "2024-01-15T10:00:00Z",
        }
        tick = parse_option_quote(msg)
        assert tick.symbol == "AAPL250321P00200000"
        assert tick.bid_price == 5.40
        assert tick.ask_price == 5.60
        assert tick.conditions == ["A"]
