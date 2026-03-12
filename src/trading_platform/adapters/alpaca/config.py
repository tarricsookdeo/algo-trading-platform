"""Alpaca-specific configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlpacaConfig:
    """Connection parameters for Alpaca APIs."""
    api_key: str
    api_secret: str
    feed: str = "sip"
    stock_ws_url: str = "wss://stream.data.alpaca.markets/v2/sip"
    options_ws_url: str = "wss://stream.data.alpaca.markets/v1beta1/opra"
    rest_base_url: str = "https://data.alpaca.markets"
    trading_base_url: str = "https://api.alpaca.markets"
