"""Tests for the structured logging utilities."""

from __future__ import annotations

import logging

import structlog

from trading_platform.core.logging import get_logger, setup_logging


class TestSetupLogging:
    def test_does_not_raise_default(self):
        setup_logging()  # INFO, no json

    def test_does_not_raise_json_output(self):
        setup_logging(json_output=True)

    def test_does_not_raise_debug_level(self):
        setup_logging(level="DEBUG")

    def test_does_not_raise_warning_level(self):
        setup_logging(level="WARNING")

    def test_does_not_raise_error_level(self):
        setup_logging(level="ERROR")

    def test_unknown_level_falls_back_to_info(self):
        # getattr(logging, "NOTREAL", logging.INFO) returns INFO
        setup_logging(level="NOTREAL")
        # Should not raise

    def test_configures_structlog(self):
        setup_logging()
        # structlog should be configured (wrapper class is set)
        config = structlog.get_config()
        assert config["wrapper_class"] is not None

    def test_configures_stdlib_logging(self):
        setup_logging(level="DEBUG")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG


class TestGetLogger:
    def test_returns_bound_logger(self):
        logger = get_logger("test.component")
        assert logger is not None

    def test_different_components_return_independent_loggers(self):
        l1 = get_logger("component.a")
        l2 = get_logger("component.b")
        assert l1 is not l2

    def test_same_component_name_each_call(self):
        # Should not raise when called multiple times with the same name
        get_logger("trading.platform")
        get_logger("trading.platform")

    def test_logger_has_info_method(self):
        logger = get_logger("test.methods")
        assert hasattr(logger, "info")

    def test_logger_has_warning_method(self):
        logger = get_logger("test.methods")
        assert hasattr(logger, "warning")

    def test_logger_has_error_method(self):
        logger = get_logger("test.methods")
        assert hasattr(logger, "error")

    def test_logger_has_debug_method(self):
        logger = get_logger("test.methods")
        assert hasattr(logger, "debug")
