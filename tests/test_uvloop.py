"""Tests for uvloop integration and fallback behavior."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from trading_platform.main import _install_uvloop


class TestUvloopInstall:
    """Test the _install_uvloop helper."""

    def test_uvloop_installs_when_available(self, tmp_path: Path) -> None:
        """uvloop.install() is called when uvloop is importable and config enables it."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[performance]\nuse_uvloop = true\n')

        # _install_uvloop should succeed (uvloop is installed in test env)
        result = _install_uvloop(config_file)
        assert result is True

        # Verify uvloop policy is active
        loop = asyncio.new_event_loop()
        try:
            assert "uvloop" in type(loop).__module__
        finally:
            loop.close()

    def test_uvloop_disabled_by_config(self, tmp_path: Path) -> None:
        """uvloop is NOT installed when use_uvloop = false."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[performance]\nuse_uvloop = false\n')

        result = _install_uvloop(config_file)
        assert result is False

    def test_uvloop_fallback_when_not_importable(self, tmp_path: Path) -> None:
        """Falls back gracefully when uvloop is not installed."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[performance]\nuse_uvloop = true\n')

        # Simulate uvloop not being installed
        with patch.dict(sys.modules, {"uvloop": None}):
            result = _install_uvloop(config_file)
            assert result is False

    def test_uvloop_default_when_no_config(self, tmp_path: Path) -> None:
        """Defaults to trying uvloop when config file doesn't exist."""
        config_file = tmp_path / "nonexistent.toml"

        # Should try to import uvloop (which is available in test env)
        result = _install_uvloop(config_file)
        assert result is True

    def test_uvloop_default_when_no_performance_section(self, tmp_path: Path) -> None:
        """Defaults to trying uvloop when [performance] section is absent."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[platform]\nlog_level = "DEBUG"\n')

        result = _install_uvloop(config_file)
        assert result is True


class TestUvloopConfigOption:
    """Test that the use_uvloop config option is properly loaded."""

    def test_performance_settings_default(self) -> None:
        from trading_platform.core.config import PerformanceSettings

        settings = PerformanceSettings()
        assert settings.use_uvloop is True

    def test_performance_settings_disabled(self) -> None:
        from trading_platform.core.config import PerformanceSettings

        settings = PerformanceSettings(use_uvloop=False)
        assert settings.use_uvloop is False

    def test_load_settings_with_uvloop(self, tmp_path: Path) -> None:
        from trading_platform.core.config import load_settings

        config_file = tmp_path / "config.toml"
        config_file.write_text('[performance]\nuse_uvloop = false\n')

        settings = load_settings(config_file)
        assert settings.performance.use_uvloop is False
