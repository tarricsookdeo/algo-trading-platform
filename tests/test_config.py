"""Tests for configuration loading (load_toml, load_settings)."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_platform.core.config import (
    DataSettings,
    DashboardSettings,
    ExpirationSettings,
    GreeksRiskSettings,
    OptionsSettings,
    PerformanceSettings,
    PlatformSettings,
    PublicComSettings,
    RiskSettings,
    Settings,
    load_settings,
    load_toml,
)


# ── load_toml ────────────────────────────────────────────────────────


class TestLoadToml:
    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        result = load_toml(tmp_path / "nonexistent.toml")
        assert result == {}

    def test_loads_valid_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[platform]\nlog_level = "DEBUG"\n')
        result = load_toml(toml_file)
        assert result["platform"]["log_level"] == "DEBUG"

    def test_loads_nested_sections(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[risk]\nmax_position_size = 500.0\n\n"
            "[risk.greeks]\nmax_portfolio_delta = 100.0\n"
        )
        result = load_toml(toml_file)
        assert result["risk"]["max_position_size"] == 500.0
        assert result["risk"]["greeks"]["max_portfolio_delta"] == 100.0

    def test_loads_multiple_sections(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[data]\ningestion_enabled = false\n\n"
            "[dashboard]\nport = 9090\n"
        )
        result = load_toml(toml_file)
        assert result["data"]["ingestion_enabled"] is False
        assert result["dashboard"]["port"] == 9090


# ── load_settings defaults ───────────────────────────────────────────


class TestLoadSettingsDefaults:
    def test_returns_settings_instance(self, tmp_path):
        settings = load_settings(tmp_path / "nonexistent.toml")
        assert isinstance(settings, Settings)

    def test_default_risk_settings(self, tmp_path):
        settings = load_settings(tmp_path / "nonexistent.toml")
        assert settings.risk.max_position_size == 1000.0
        assert settings.risk.max_order_value == 50000.0
        assert settings.risk.daily_loss_limit == -5000.0
        assert settings.risk.max_open_orders == 20

    def test_default_platform_settings(self, tmp_path):
        settings = load_settings(tmp_path / "nonexistent.toml")
        assert "AAPL" in settings.platform.symbols
        assert settings.platform.log_level == "INFO"

    def test_default_dashboard_settings(self, tmp_path):
        settings = load_settings(tmp_path / "nonexistent.toml")
        assert settings.dashboard.port == 8080
        assert settings.dashboard.update_interval_ms == 100

    def test_default_performance_settings(self, tmp_path):
        settings = load_settings(tmp_path / "nonexistent.toml")
        assert settings.performance.message_queue_size == 50000
        assert settings.performance.consumer_batch_size == 100

    def test_default_expiration_settings(self, tmp_path):
        settings = load_settings(tmp_path / "nonexistent.toml")
        assert settings.options.expiration.auto_close_dte == 1
        assert settings.options.expiration.alert_dte == 7

    def test_default_greeks_settings(self, tmp_path):
        settings = load_settings(tmp_path / "nonexistent.toml")
        assert settings.risk.greeks.max_portfolio_delta == 500.0
        assert settings.risk.greeks.max_portfolio_vega == 1000.0


# ── load_settings from TOML ──────────────────────────────────────────


class TestLoadSettingsFromToml:
    def test_loads_risk_section(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[risk]\n"
            "max_position_size = 500.0\n"
            "daily_loss_limit = -2000.0\n"
            "max_open_orders = 10\n"
        )
        settings = load_settings(toml_file)
        assert settings.risk.max_position_size == 500.0
        assert settings.risk.daily_loss_limit == -2000.0
        assert settings.risk.max_open_orders == 10

    def test_loads_nested_risk_greeks(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[risk.greeks]\n"
            "max_portfolio_delta = 200.0\n"
            "max_portfolio_gamma = 50.0\n"
            "max_daily_theta = -100.0\n"
        )
        settings = load_settings(toml_file)
        assert settings.risk.greeks.max_portfolio_delta == 200.0
        assert settings.risk.greeks.max_portfolio_gamma == 50.0
        assert settings.risk.greeks.max_daily_theta == -100.0

    def test_loads_nested_options_expiration(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[options.expiration]\n"
            "auto_close_dte = 2\n"
            "alert_dte = 14\n"
            "roll_enabled = true\n"
            "roll_target_dte = 45\n"
        )
        settings = load_settings(toml_file)
        assert settings.options.expiration.auto_close_dte == 2
        assert settings.options.expiration.alert_dte == 14
        assert settings.options.expiration.roll_enabled is True
        assert settings.options.expiration.roll_target_dte == 45

    def test_loads_dashboard_section(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[dashboard]\n"
            "port = 9090\n"
            "update_interval_ms = 200\n"
        )
        settings = load_settings(toml_file)
        assert settings.dashboard.port == 9090
        assert settings.dashboard.update_interval_ms == 200

    def test_loads_data_section(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[data]\n"
            "ingestion_enabled = false\n"
            "max_bars_per_request = 5000\n"
        )
        settings = load_settings(toml_file)
        assert settings.data.ingestion_enabled is False
        assert settings.data.max_bars_per_request == 5000

    def test_loads_performance_section(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[performance]\n"
            "message_queue_size = 10000\n"
            "consumer_batch_size = 50\n"
            "default_serialization = \"msgpack\"\n"
        )
        settings = load_settings(toml_file)
        assert settings.performance.message_queue_size == 10000
        assert settings.performance.consumer_batch_size == 50
        assert settings.performance.default_serialization == "msgpack"

    def test_loads_platform_symbols(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[platform]\n'
            'symbols = ["SPY", "QQQ"]\n'
            'log_level = "DEBUG"\n'
        )
        settings = load_settings(toml_file)
        assert settings.platform.symbols == ["SPY", "QQQ"]
        assert settings.platform.log_level == "DEBUG"

    def test_greeks_not_in_risk_after_pop(self, tmp_path):
        """Nested [risk.greeks] must not be passed through to RiskSettings directly."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[risk]\nmax_position_size = 250.0\n\n"
            "[risk.greeks]\nmax_portfolio_delta = 100.0\n"
        )
        # Should not raise a validation error about unexpected 'greeks' key in RiskSettings
        settings = load_settings(toml_file)
        assert settings.risk.max_position_size == 250.0
        assert settings.risk.greeks.max_portfolio_delta == 100.0

    def test_expiration_not_in_options_after_pop(self, tmp_path):
        """Nested [options.expiration] must not be passed through to OptionsSettings directly."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[options]\npoll_interval = 5.0\n\n"
            "[options.expiration]\nauto_close_dte = 3\n"
        )
        settings = load_settings(toml_file)
        assert settings.options.poll_interval == 5.0
        assert settings.options.expiration.auto_close_dte == 3

    def test_explicit_config_path_takes_precedence(self, tmp_path):
        toml_file = tmp_path / "custom.toml"
        toml_file.write_text("[dashboard]\nport = 7777\n")
        settings = load_settings(toml_file)
        assert settings.dashboard.port == 7777

    def test_missing_explicit_path_uses_defaults(self, tmp_path):
        settings = load_settings(tmp_path / "missing.toml")
        assert settings.dashboard.port == 8080  # default


# ── Individual Settings model defaults ───────────────────────────────


class TestIndividualSettingsModels:
    def test_data_settings_defaults(self):
        s = DataSettings()
        assert s.ingestion_enabled is True
        assert s.replay_speed == 0.0
        assert s.max_bars_per_request == 10000

    def test_performance_settings_defaults(self):
        s = PerformanceSettings()
        assert s.message_queue_mode == "lossy"
        assert s.dedup_quotes_in_batch is True
        assert s.lazy_deserialize is False

    def test_dashboard_settings_defaults(self):
        s = DashboardSettings()
        assert s.host == "0.0.0.0"
        assert s.max_trades_per_flush == 50

    def test_expiration_settings_defaults(self):
        s = ExpirationSettings()
        assert s.roll_enabled is False
        assert s.check_interval_seconds == 60.0

    def test_greeks_risk_settings_defaults(self):
        s = GreeksRiskSettings()
        assert s.max_portfolio_delta == 500.0
        assert s.greeks_refresh_interval_seconds == 30.0

    def test_risk_settings_blocked_symbols(self):
        s = RiskSettings(blocked_symbols=["MEME", "GME"])
        assert "MEME" in s.blocked_symbols

    def test_platform_settings_default_symbols(self):
        s = PlatformSettings()
        assert "AAPL" in s.symbols
