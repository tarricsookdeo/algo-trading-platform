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


class DataSettings(BaseSettings):
    ingestion_enabled: bool = True
    csv_directory: str = ""
    replay_speed: float = 0.0
    max_bars_per_request: int = 10000


class PerformanceSettings(BaseSettings):
    message_queue_size: int = 50000
    message_queue_mode: str = "lossy"
    consumer_batch_size: int = 100
    consumer_flush_interval_ms: int = 10
    dedup_quotes_in_batch: bool = True
    default_serialization: str = "json"
    lazy_deserialize: bool = False


class DashboardSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8080
    update_interval_ms: int = 100
    max_trades_per_flush: int = 50


class PublicComSettings(BaseSettings):
    api_secret: str = Field(default="", alias="PUBLIC_API_SECRET")
    account_id: str = Field(default="", alias="PUBLIC_ACCOUNT_ID")
    poll_interval: float = 2.0
    portfolio_refresh: float = 30.0


class GreeksRiskSettings(BaseSettings):
    max_portfolio_delta: float = 500.0
    max_portfolio_gamma: float = 100.0
    max_daily_theta: float = -200.0
    max_portfolio_vega: float = 1000.0
    greeks_refresh_interval_seconds: float = 30.0


class RiskSettings(BaseSettings):
    max_position_size: float = 1000.0
    max_position_concentration: float = 0.10
    max_order_value: float = 50000.0
    daily_loss_limit: float = -5000.0
    max_open_orders: int = 20
    max_daily_trades: int = 100
    max_portfolio_drawdown: float = 0.15
    allowed_symbols: list[str] = Field(default_factory=list)
    blocked_symbols: list[str] = Field(default_factory=list)
    greeks: GreeksRiskSettings = Field(default_factory=GreeksRiskSettings)


class CryptoSettings(BaseSettings):
    api_secret: str = Field(default="", alias="PUBLIC_API_SECRET")
    account_id: str = Field(default="", alias="PUBLIC_ACCOUNT_ID")
    trading_pairs: list[str] = Field(default_factory=lambda: ["BTC-USD", "ETH-USD"])
    poll_interval: float = 2.0
    portfolio_refresh: float = 30.0


class ExpirationSettings(BaseSettings):
    auto_close_dte: int = 1
    alert_dte: int = 7
    roll_enabled: bool = False
    roll_target_dte: int = 30
    check_interval_seconds: float = 60.0


class OptionsSettings(BaseSettings):
    poll_interval: float = 2.0
    portfolio_refresh: float = 30.0
    expiration: ExpirationSettings = Field(default_factory=ExpirationSettings)


class PlatformSettings(BaseSettings):
    log_level: str = "INFO"
    symbols: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"])


class Settings(BaseSettings):
    data: DataSettings = Field(default_factory=DataSettings)
    public_com: PublicComSettings = Field(default_factory=PublicComSettings)
    crypto: CryptoSettings = Field(default_factory=CryptoSettings)
    options: OptionsSettings = Field(default_factory=OptionsSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    platform: PlatformSettings = Field(default_factory=PlatformSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)

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

    data_cfg = DataSettings(**toml_data.get("data", {}))
    public_com_data = toml_data.get("public_com", {})
    crypto_data = toml_data.get("crypto", {})
    dashboard_data = toml_data.get("dashboard", {})
    platform_data = toml_data.get("platform", {})
    performance_data = toml_data.get("performance", {})
    risk_data = dict(toml_data.get("risk", {}))

    options_data = dict(toml_data.get("options", {}))

    # Handle nested TOML sections: [risk.greeks] and [options.expiration]
    greeks_data = risk_data.pop("greeks", {})
    greeks_settings = GreeksRiskSettings(**greeks_data)

    expiration_data = options_data.pop("expiration", {})
    expiration_settings = ExpirationSettings(**expiration_data)

    public_com = PublicComSettings(**public_com_data)
    crypto = CryptoSettings(**crypto_data)
    options = OptionsSettings(**options_data, expiration=expiration_settings)
    dashboard = DashboardSettings(**dashboard_data)
    platform_cfg = PlatformSettings(**platform_data)
    performance = PerformanceSettings(**performance_data)
    risk = RiskSettings(**risk_data, greeks=greeks_settings)

    return Settings(
        data=data_cfg,
        public_com=public_com,
        crypto=crypto,
        options=options,
        dashboard=dashboard,
        platform=platform_cfg,
        risk=risk,
        performance=performance,
    )
