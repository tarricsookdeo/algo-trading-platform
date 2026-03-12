# Algo Trading Platform Documentation

Comprehensive documentation for the algo trading platform — a production-oriented, event-driven system for live algorithmic trading with real-time market data, automated execution, strategy management, and risk controls.

## Documentation Guide

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System architecture, component design, event flow, and data pipeline |
| [Getting Started](getting-started.md) | Installation, configuration, first run, and verification |
| [Configuration](configuration.md) | Complete reference for `.env`, `config.toml`, and all settings |
| [Adapters](adapters.md) | Alpaca data adapter and Public.com execution adapter |
| [Strategies](strategies.md) | Strategy development guide with lifecycle, context API, and examples |
| [Risk Management](risk-management.md) | Pre-trade checks, post-trade monitoring, halts, and configuration |
| [Dashboard](dashboard.md) | Web dashboard panels, REST API, and WebSocket API reference |
| [Event Bus](event-bus.md) | Event bus API, all channels with payload schemas, wildcard subscriptions |
| [API Reference](api-reference.md) | Quick reference for all public classes, methods, and enums |

## Examples

Runnable example scripts in [`examples/`](examples/):

| Script | Description |
|--------|-------------|
| [`basic_streaming.py`](examples/basic_streaming.py) | Connect to Alpaca and stream real-time quotes |
| [`place_equity_order.py`](examples/place_equity_order.py) | Place equity orders via Public.com (market, limit, stop) |
| [`place_option_order.py`](examples/place_option_order.py) | Place single-leg option orders |
| [`place_spread_order.py`](examples/place_spread_order.py) | Place multi-leg spread orders |
| [`custom_strategy.py`](examples/custom_strategy.py) | Complete mean reversion strategy example |
| [`risk_configuration.py`](examples/risk_configuration.py) | Configure and test risk controls programmatically |
| [`portfolio_monitor.py`](examples/portfolio_monitor.py) | Fetch and display portfolio positions with P&L |
| [`event_listener.py`](examples/event_listener.py) | Subscribe to event bus channels and log events |
| [`backtest_data_collection.py`](examples/backtest_data_collection.py) | Collect historical bars for offline analysis |

## Platform Overview

The platform implements:

- **Real-time market data** — SIP stock and OPRA options streams via Alpaca WebSocket
- **Live order execution** — Equities, options, and multi-leg spreads via Public.com
- **Strategy framework** — Abstract base class with lifecycle management and event wiring
- **Risk management** — 6 pre-trade checks, 2 post-trade checks, automatic trading halts
- **Monitoring dashboard** — Real-time web UI with REST and WebSocket APIs

## Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Core infrastructure (EventBus, models, config, logging) | Complete |
| 2 | Alpaca market data (SIP/OPRA streams, REST, dashboard) | Complete |
| 3 | Public.com execution adapter | Complete |
| 4 | Coinbase Advanced Trade adapter | Planned |
| 5 | Strategy framework | Complete |
| 6 | Risk controls | Complete |
| 7 | Dashboard enhancements (portfolio, orders, strategies, risk, P&L) | Complete |
