"""Platform entry point.

Boots the event bus, data manager, Public.com exec adapter, risk manager,
strategy manager, and dashboard. Handles graceful shutdown on SIGINT / SIGTERM.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

import uvicorn

from trading_platform.adapters.crypto.adapter import CryptoExecAdapter
from trading_platform.adapters.crypto.config import CryptoConfig
from trading_platform.adapters.options.adapter import OptionsExecAdapter
from trading_platform.adapters.options.config import OptionsConfig
from trading_platform.adapters.public_com.adapter import PublicComExecAdapter
from trading_platform.adapters.public_com.config import PublicComConfig
from trading_platform.bracket.manager import BracketOrderManager
from trading_platform.core.config import load_settings
from trading_platform.core.enums import AssetClass, Channel
from trading_platform.core.message_queue import MessageQueue
from trading_platform.core.metrics import PerformanceMetrics
from trading_platform.core.order_router import OrderRouter
from trading_platform.core.events import EventBus
from trading_platform.core.logging import get_logger, setup_logging
from trading_platform.dashboard.app import create_app
from trading_platform.dashboard.throttler import DashboardThrottler
from trading_platform.dashboard.ws import DashboardWSManager
from trading_platform.data.config import DataConfig
from trading_platform.data.file_provider import CsvBarProvider
from trading_platform.data.manager import DataManager
from trading_platform.options.expiration import ExpirationConfig, ExpirationManager
from trading_platform.options.greeks import GreeksProvider
from trading_platform.risk.greeks_checks import GreeksRiskConfig
from trading_platform.risk.manager import RiskManager
from trading_platform.risk.models import RiskConfig
from trading_platform.strategy.manager import StrategyManager

BANNER = r"""
    _    _             _____              _ _
   / \  | | __ _  ___ |_   _| __ __ _  __| (_)_ __   __ _
  / _ \ | |/ _` |/ _ \  | || '__/ _` |/ _` | | '_ \ / _` |
 / ___ \| | (_| | (_) | | || | | (_| | (_| | | | | | (_| |
/_/   \_\_|\__, |\___/  |_||_|  \__,_|\__,_|_|_| |_|\__, |
           |___/                                     |___/
           P L A T F O R M   v0.3.0
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Algo Trading Platform")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to config.toml",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    """Async main loop."""
    # ── Configuration ──────────────────────────────────────────────────
    settings = load_settings(args.config)
    log_level = args.log_level or settings.platform.log_level
    setup_logging(level=log_level)
    log = get_logger("platform.main")

    print(BANNER)
    log.info(
        "starting platform",
        symbols=settings.platform.symbols,
        dashboard_port=settings.dashboard.port,
    )

    # ── Core ───────────────────────────────────────────────────────────
    event_bus = EventBus()

    # ── Performance Metrics ────────────────────────────────────────────
    perf_metrics = PerformanceMetrics()
    log.info("performance metrics initialized")

    # ── Message Queue ──────────────────────────────────────────────────
    message_queue = MessageQueue(
        max_size=settings.performance.message_queue_size,
        mode=settings.performance.message_queue_mode,
        dedup_quotes=settings.performance.dedup_quotes_in_batch,
    )

    async def _mq_consumer_callback(batch: list[dict[str, Any]]) -> None:
        """Republish queued messages to the EventBus."""
        for msg in batch:
            channel = msg.pop("_channel", None)
            if channel:
                await event_bus.publish(channel, msg)
                perf_metrics.record_processed()

    message_queue.start_consumer(
        callback=_mq_consumer_callback,
        batch_size=settings.performance.consumer_batch_size,
        flush_interval_ms=settings.performance.consumer_flush_interval_ms,
    )
    log.info(
        "message queue started",
        mode=settings.performance.message_queue_mode,
        max_size=settings.performance.message_queue_size,
    )

    # ── Data Manager ──────────────────────────────────────────────────
    data_config = DataConfig(
        ingestion_enabled=settings.data.ingestion_enabled,
        csv_directory=settings.data.csv_directory,
        replay_speed=settings.data.replay_speed,
        max_bars_per_request=settings.data.max_bars_per_request,
    )
    data_manager = DataManager(
        event_bus,
        data_config,
        message_queue=message_queue,
        perf_metrics=perf_metrics,
    )

    # Register file providers if directories are configured
    if data_config.csv_directory:
        csv_provider = CsvBarProvider(
            data_config.csv_directory, replay_speed=data_config.replay_speed
        )
        data_manager.register_provider(csv_provider)

    # ── Order Router & Exec Adapters ──────────────────────────────────
    order_router = OrderRouter()
    equity_adapter: PublicComExecAdapter | None = None
    crypto_adapter: CryptoExecAdapter | None = None

    options_adapter: OptionsExecAdapter | None = None

    if settings.public_com.api_secret and settings.public_com.account_id:
        public_config = PublicComConfig(
            api_secret=settings.public_com.api_secret,
            account_id=settings.public_com.account_id,
            poll_interval=settings.public_com.poll_interval,
            portfolio_refresh=settings.public_com.portfolio_refresh,
        )
        equity_adapter = PublicComExecAdapter(public_config, event_bus)
        order_router.register(AssetClass.EQUITY, equity_adapter)
        log.info("public.com equity adapter configured")

        # Register dedicated options adapter (shares credentials with equity)
        opts_cfg = OptionsConfig(
            api_secret=settings.public_com.api_secret,
            account_id=settings.public_com.account_id,
            poll_interval=settings.options.poll_interval,
            portfolio_refresh=settings.options.portfolio_refresh,
        )
        options_adapter = OptionsExecAdapter(opts_cfg, event_bus)
        order_router.register(AssetClass.OPTION, options_adapter)
        log.info("options adapter configured")
    else:
        log.info("public.com equity adapter skipped (no credentials)")

    if settings.crypto.api_secret:
        crypto_config = CryptoConfig(
            api_secret=settings.crypto.api_secret,
            account_id=settings.crypto.account_id,
            trading_pairs=settings.crypto.trading_pairs,
            poll_interval=settings.crypto.poll_interval,
            portfolio_refresh=settings.crypto.portfolio_refresh,
        )
        crypto_adapter = CryptoExecAdapter(crypto_config, event_bus)
        order_router.register(AssetClass.CRYPTO, crypto_adapter)
        log.info("crypto adapter configured")
    else:
        log.info("crypto adapter skipped (no credentials)")

    # Use order_router as the unified exec adapter
    exec_adapter = order_router if order_router._adapters else None

    # ── Risk Manager ───────────────────────────────────────────────────
    risk_config = RiskConfig(
        max_position_size=settings.risk.max_position_size,
        max_position_concentration=settings.risk.max_position_concentration,
        max_order_value=settings.risk.max_order_value,
        daily_loss_limit=settings.risk.daily_loss_limit,
        max_open_orders=settings.risk.max_open_orders,
        max_daily_trades=settings.risk.max_daily_trades,
        max_portfolio_drawdown=settings.risk.max_portfolio_drawdown,
        allowed_symbols=settings.risk.allowed_symbols,
        blocked_symbols=settings.risk.blocked_symbols,
    )
    risk_manager = RiskManager(risk_config, event_bus)
    log.info("risk manager initialized")

    # ── Greeks-Aware Risk (optional, requires options adapter) ────────
    greeks_provider: GreeksProvider | None = None
    if options_adapter is not None:
        greeks_provider = GreeksProvider(
            client=options_adapter,
            refresh_interval=settings.risk.greeks.greeks_refresh_interval_seconds,
        )
        greeks_risk_cfg = GreeksRiskConfig(
            max_portfolio_delta=settings.risk.greeks.max_portfolio_delta,
            max_portfolio_gamma=settings.risk.greeks.max_portfolio_gamma,
            max_daily_theta=settings.risk.greeks.max_daily_theta,
            max_portfolio_vega=settings.risk.greeks.max_portfolio_vega,
        )
        risk_manager.register_greeks_checks(greeks_provider, greeks_risk_cfg)
        log.info("greeks-aware risk checks registered")

    # ── Expiration Manager ─────────────────────────────────────────────
    expiration_config = ExpirationConfig(
        auto_close_dte=settings.options.expiration.auto_close_dte,
        alert_dte=settings.options.expiration.alert_dte,
        roll_enabled=settings.options.expiration.roll_enabled,
        roll_target_dte=settings.options.expiration.roll_target_dte,
        check_interval_seconds=settings.options.expiration.check_interval_seconds,
    )
    expiration_manager = ExpirationManager(
        config=expiration_config,
        event_bus=event_bus,
        exec_adapter=options_adapter,
    )
    log.info("expiration manager initialized")

    # ── Bracket Order Manager ─────────────────────────────────────────
    bracket_manager = BracketOrderManager(event_bus=event_bus, exec_adapter=exec_adapter)
    log.info("bracket order manager initialized")

    # ── Strategy Manager ───────────────────────────────────────────────
    strategy_manager = StrategyManager(
        event_bus=event_bus,
        exec_adapter=exec_adapter,
        risk_manager=risk_manager,
        bracket_manager=bracket_manager,
    )
    log.info("strategy manager initialized")

    # ── Dashboard Throttler ────────────────────────────────────────────
    throttler = DashboardThrottler(
        flush_interval_ms=settings.dashboard.update_interval_ms,
        max_trades_per_flush=settings.dashboard.max_trades_per_flush,
    )
    log.info(
        "dashboard throttler configured",
        interval_ms=settings.dashboard.update_interval_ms,
    )

    # ── Dashboard ──────────────────────────────────────────────────────
    app, ws_manager = create_app(
        event_bus,
        data_manager=data_manager,
        exec_adapter=exec_adapter,
        strategy_manager=strategy_manager,
        risk_manager=risk_manager,
        message_queue=message_queue,
        perf_metrics=perf_metrics,
        throttler=throttler,
    )

    # ── Shutdown handling ──────────────────────────────────────────────
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # ── Start everything ───────────────────────────────────────────────
    try:
        await data_manager.start()
        log.info("data manager started")

        # Connect exec adapters if configured
        if exec_adapter:
            await exec_adapter.connect()
            log.info("exec adapters connected")

        # Start expiration manager
        await expiration_manager.start()
        log.info("expiration manager started")

        # Wire bracket and strategy manager events
        await bracket_manager.wire_events()
        log.info("bracket order manager events wired")
        await strategy_manager.wire_events()
        log.info("strategy manager events wired")

        # Start WS manager
        await ws_manager.start()

        # Start uvicorn as a task
        uvi_config = uvicorn.Config(
            app,
            host=settings.dashboard.host,
            port=settings.dashboard.port,
            log_level=log_level.lower(),
            access_log=False,
        )
        server = uvicorn.Server(uvi_config)
        server_task = asyncio.create_task(server.serve())

        await event_bus.publish(
            Channel.SYSTEM,
            {
                "component": "platform",
                "message": f"dashboard running on http://{settings.dashboard.host}:{settings.dashboard.port}",
                "level": "info",
            },
        )
        log.info(
            "platform ready",
            dashboard=f"http://{settings.dashboard.host}:{settings.dashboard.port}",
        )

        # Wait for shutdown signal
        await shutdown_event.wait()

    finally:
        log.info("shutting down platform")
        await expiration_manager.stop()
        await strategy_manager.stop_all()
        await strategy_manager.unwire_events()
        await bracket_manager.unwire_events()
        await ws_manager.stop()
        await message_queue.stop()
        if exec_adapter:
            await exec_adapter.disconnect()
        await data_manager.stop()
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        log.info("platform stopped")


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
