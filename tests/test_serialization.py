"""Tests for data serialization helpers (JSON and MessagePack)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from trading_platform.data.serialization import (
    Format,
    deserialize,
    detect_format,
    has_msgpack,
    serialize,
)


# ── Format enum ──────────────────────────────────────────────────────


class TestFormatEnum:
    def test_json_value(self):
        assert Format.JSON == "json"

    def test_msgpack_value(self):
        assert Format.MSGPACK == "msgpack"


# ── serialize / deserialize (JSON) ───────────────────────────────────


class TestJsonRoundtrip:
    def test_serialize_dict(self):
        data = {"symbol": "AAPL", "price": 150.0}
        raw = serialize(data)
        assert isinstance(raw, bytes)
        assert json.loads(raw) == data

    def test_serialize_list(self):
        data = [1, 2, 3]
        raw = serialize(data, Format.JSON)
        assert deserialize(raw, Format.JSON) == data

    def test_serialize_nested(self):
        data = {"legs": [{"side": "buy", "qty": 1}, {"side": "sell", "qty": 1}]}
        raw = serialize(data)
        assert deserialize(raw) == data

    def test_json_is_default_format(self):
        data = {"key": "value"}
        # No fmt argument — should default to JSON
        raw = serialize(data)
        assert deserialize(raw) == data

    def test_serialize_produces_utf8(self):
        raw = serialize({"msg": "hello"})
        assert raw.decode("utf-8")

    def test_empty_dict(self):
        assert deserialize(serialize({})) == {}

    def test_empty_list(self):
        assert deserialize(serialize([])) == []


# ── serialize / deserialize (MessagePack) ────────────────────────────


class TestMsgpackRoundtrip:
    @pytest.fixture(autouse=True)
    def skip_if_no_msgpack(self):
        if not has_msgpack():
            pytest.skip("msgpack not installed")

    def test_serialize_dict(self):
        data = {"symbol": "BTC-USD", "price": 42000.0}
        raw = serialize(data, Format.MSGPACK)
        assert isinstance(raw, bytes)
        assert deserialize(raw, Format.MSGPACK) == data

    def test_serialize_list(self):
        data = [{"a": 1}, {"b": 2}]
        raw = serialize(data, Format.MSGPACK)
        assert deserialize(raw, Format.MSGPACK) == data

    def test_msgpack_is_binary_and_smaller_than_json(self):
        data = {"symbol": "AAPL", "bid": 149.99, "ask": 150.01, "volume": 1_000_000}
        json_raw = serialize(data, Format.JSON)
        mp_raw = serialize(data, Format.MSGPACK)
        # msgpack should be more compact than JSON for typical payloads
        assert len(mp_raw) < len(json_raw)

    def test_msgpack_nested(self):
        data = {"bars": [{"open": 100, "close": 101, "high": 102, "low": 99}] * 5}
        raw = serialize(data, Format.MSGPACK)
        assert deserialize(raw, Format.MSGPACK) == data


class TestMsgpackUnavailable:
    def test_serialize_raises_when_no_msgpack(self):
        with patch("trading_platform.data.serialization._HAS_MSGPACK", False):
            with pytest.raises(RuntimeError, match="msgpack package is not installed"):
                serialize({"x": 1}, Format.MSGPACK)

    def test_deserialize_raises_when_no_msgpack(self):
        with patch("trading_platform.data.serialization._HAS_MSGPACK", False):
            with pytest.raises(RuntimeError, match="msgpack package is not installed"):
                deserialize(b"\x81\xa1x\x01", Format.MSGPACK)


# ── detect_format ────────────────────────────────────────────────────


class TestDetectFormat:
    def test_none_defaults_to_json(self):
        assert detect_format(None) == Format.JSON

    def test_empty_string_defaults_to_json(self):
        assert detect_format("") == Format.JSON

    def test_json_content_type(self):
        assert detect_format("application/json") == Format.JSON

    def test_json_with_charset(self):
        assert detect_format("application/json; charset=utf-8") == Format.JSON

    def test_msgpack_content_type(self):
        assert detect_format("application/x-msgpack") == Format.MSGPACK

    def test_msgpack_with_charset(self):
        assert detect_format("application/x-msgpack; charset=utf-8") == Format.MSGPACK

    def test_unknown_content_type_defaults_to_json(self):
        assert detect_format("text/plain") == Format.JSON

    def test_partial_msgpack_match(self):
        # "msgpack" substring anywhere in the content type should match
        assert detect_format("application/msgpack") == Format.MSGPACK


# ── has_msgpack ───────────────────────────────────────────────────────


class TestHasMsgpack:
    def test_returns_bool(self):
        result = has_msgpack()
        assert isinstance(result, bool)

    def test_returns_true_when_available(self):
        with patch("trading_platform.data.serialization._HAS_MSGPACK", True):
            assert has_msgpack() is True

    def test_returns_false_when_unavailable(self):
        with patch("trading_platform.data.serialization._HAS_MSGPACK", False):
            assert has_msgpack() is False
