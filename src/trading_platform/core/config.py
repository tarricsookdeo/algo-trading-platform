"""Configuration management.

Loads secrets from .env and platform settings from config.toml.
Environment variables override TOML values.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class AlpacaSettings(BaseSettings):
    api_key: str = Field(default="", alias="ALPACA_API_KEY")
    api_secret: str = Field(default="", alias="ALPACA_API_SECRET")
    feed: str = "sip"
    base_url: str = "https://data.alpaca.markets"
    trading_base_url: str = "https://api.alpaca.markets"
    stock_ws_url: str = "wss://stream.data.alpaca.markets/v2/sip"
    options_ws_url: str = "wss://stream.data.alpaca.markets/v1beta1/opra"


class DashboardSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8080


class PlatformSettings(BaseSettings):
    log_level: str = "INFO"
    symbols: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"])


class Settings(BaseSettings):
    alpaca: AlpacaSettings = Field(default_factory=AlpacaSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    platform: PlatformSettings = Field(default_factory=PlatformSettings)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dict."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from .env + config.toml, with env var overrides.

    Reads TOML for defaults, then layers environment variables on top
    via Pydantic Settings.
    """
    toml_data: dict[str, Any] = {}
    if config_path and config_path.exists():
        toml_data = load_toml(config_path)
    else:
        default_path = Path("config.toml")
        if default_path.exists():
            toml_data = load_toml(default_path)

    alpaca_data = toml_data.get("alpaca", {})
    dashboard_data = toml_data.get("dashboard", {})
    platform_data = toml_data.get("platform", {})

    alpaca = AlpacaSettings(**alpaca_data)
    dashboard = DashboardSettings(**dashboard_data)
    platform_cfg = PlatformSettings(**platform_data)

    return Settings(alpaca=alpaca, dashboard=dashboard, platform=platform_cfg)
