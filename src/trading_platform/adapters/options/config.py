"""Configuration for the options execution adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OptionsConfig:
    """Options adapter configuration."""

    api_secret: str = ""
    account_id: str = ""
    poll_interval: float = 2.0
    portfolio_refresh: float = 30.0
    token_validity_minutes: int = 15
