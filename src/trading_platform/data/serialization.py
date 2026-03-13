"""Serialization helpers — JSON and MessagePack.

Provides a unified interface for serializing and deserializing data in
either JSON or MessagePack format. MessagePack is a compact binary format
that is faster to encode/decode than JSON for typical market data payloads.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

try:
    import msgpack

    _HAS_MSGPACK = True
except ImportError:  # pragma: no cover
    _HAS_MSGPACK = False


class Format(StrEnum):
    JSON = "json"
    MSGPACK = "msgpack"


def serialize(data: Any, fmt: Format = Format.JSON) -> bytes:
    """Serialize *data* to bytes in the given format."""
    if fmt == Format.MSGPACK:
        if not _HAS_MSGPACK:
            raise RuntimeError("msgpack package is not installed")
        return msgpack.packb(data, use_bin_type=True)
    return json.dumps(data).encode("utf-8")


def deserialize(raw: bytes, fmt: Format = Format.JSON) -> Any:
    """Deserialize *raw* bytes into a Python object."""
    if fmt == Format.MSGPACK:
        if not _HAS_MSGPACK:
            raise RuntimeError("msgpack package is not installed")
        return msgpack.unpackb(raw, raw=False)
    return json.loads(raw)


def detect_format(content_type: str | None) -> Format:
    """Infer serialization format from an HTTP Content-Type header value."""
    if content_type and "msgpack" in content_type:
        return Format.MSGPACK
    return Format.JSON


def has_msgpack() -> bool:
    """Return True if msgpack is available."""
    return _HAS_MSGPACK
