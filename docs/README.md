# Algo Trading Platform Documentation

Comprehensive documentation for the algo trading platform — a production-oriented, event-driven system for live algorithmic trading with bring-your-own-data ingestion, automated execution, strategy management, and risk controls.

## Documentation Guide

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System architecture, component design, event flow, and data pipeline |
| [Getting Started](getting-started.md) | Installation, configuration, first run, and verification |
| [Configuration](configuration.md) | Complete reference for `.env`, `config.toml`, and all settings |
| [Data Providers & Adapters](adapters.md) | BYOD data providers and Public.com execution adapter |
| [Strategies](strategies.md) | Strategy development guide with lifecycle, context API, and examples |
| [Risk Management](risk-management.md) | Pre-trade checks, post-trade monitoring, halts, and configuration |
| [Dashboard](dashboard.md) | Web dashboard panels, REST API, and WebSocket API reference |
| [Event Bus](event-bus.md) | Event bus API, all channels with payload schemas, wildcard subscriptions |
| [API Reference](api-reference.md) | Quick reference for all public classes, methods, and enums |

## Platform Overview

The platform implements:

- **Bring-your-own-data ingestion** — CSV/Parquet file loading, REST POST, WebSocket streaming, and custom Python providers via DataProvider ABC
- **Live order execution** — Equities, options, and multi-leg spreads via Public.com
- **Strategy framework** — Abstract base class with lifecycle management and event wiring
- **Risk management** — 6 pre-trade checks, 2 post-trade checks, automatic trading halts
- **Monitoring dashboard** — Real-time web UI with REST and WebSocket APIs

## Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Core infrastructure (EventBus, models, config, logging) | Complete |
| 2 | BYOD data ingestion (DataProvider, DataManager, file providers, REST/WS) | Complete |
| 3 | Public.com execution adapter | Complete |
| 4 | Strategy framework | Complete |
| 5 | Risk controls | Complete |
| 6 | Dashboard enhancements (portfolio, orders, strategies, risk, P&L, data ingestion) | Complete |
| 7 | Documentation | Complete |
