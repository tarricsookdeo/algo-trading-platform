"""Configuration for the crypto execution adapter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CryptoConfig:
    """Crypto adapter configuration."""

    api_secret: str = ""
    account_id: str = ""
    trading_pairs: list[str] = field(default_factory=lambda: ["BTC-USD", "ETH-USD"])
    poll_interval: float = 2.0
    portfolio_refresh: float = 30.0
    token_validity_minutes: int = 15
