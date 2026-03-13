# Greeks & Risk

## Overview

The platform provides greeks-aware risk management for options positions. The `GreeksProvider` fetches and caches greeks data, and five risk check functions enforce portfolio-level and per-position greeks limits.

## GreeksProvider

`trading_platform.options.greeks.GreeksProvider`

Fetches greeks from the broker API with caching:

```python
from trading_platform.options.greeks import GreeksProvider

provider = GreeksProvider(
    client=options_adapter,
    refresh_interval=30.0,  # Cache TTL in seconds
)

# Get greeks for a single option
greeks = await provider.get_greeks("AAPL250321C00150000")
print(greeks.delta, greeks.gamma, greeks.theta, greeks.vega)

# Get aggregated portfolio greeks
agg = await provider.get_portfolio_greeks(positions)
print(f"Portfolio delta: {agg.total_delta}")
print(f"Portfolio gamma: {agg.total_gamma}")
print(f"Portfolio theta: {agg.total_theta}")
print(f"Portfolio vega: {agg.total_vega}")

# Invalidate cache
provider.invalidate("AAPL250321C00150000")  # Single symbol
provider.invalidate()  # All cached data
```

### GreeksData

| Field | Type | Description |
|-------|------|-------------|
| `delta` | `float` | Option delta |
| `gamma` | `float` | Option gamma |
| `theta` | `float` | Option theta (daily decay) |
| `vega` | `float` | Option vega |
| `rho` | `float` | Option rho |
| `implied_volatility` | `float` | IV |
| `timestamp` | `float` | Cache timestamp |

### AggregatedGreeks

| Field | Type | Description |
|-------|------|-------------|
| `total_delta` | `float` | Sum of position deltas |
| `total_gamma` | `float` | Sum of position gammas |
| `total_theta` | `float` | Sum of position thetas |
| `total_vega` | `float` | Sum of position vegas |
| `position_count` | `int` | Number of options positions |

## Risk Checks

`trading_platform.risk.greeks_checks`

Five async check functions, each returning `tuple[bool, str]` (passed, reason):

### Portfolio Delta Check
```python
from trading_platform.risk.greeks_checks import check_portfolio_delta, GreeksRiskConfig

config = GreeksRiskConfig(max_portfolio_delta=500.0)
passed, reason = await check_portfolio_delta(provider, positions, config)
```
Ensures absolute portfolio delta stays within limits.

### Portfolio Gamma Check
```python
passed, reason = await check_portfolio_gamma(provider, positions, config)
```
Limits portfolio gamma exposure.

### Theta Decay Check
```python
config = GreeksRiskConfig(max_daily_theta=-200.0)
passed, reason = await check_theta_decay(provider, positions, config)
```
Alerts when daily theta decay exceeds threshold.

### Vega Exposure Check
```python
passed, reason = await check_vega_exposure(provider, positions, config)
```
Limits portfolio vega exposure.

### Single Position Greeks Check
```python
passed, reason = await check_single_position_greeks(provider, order, config)
```
Per-position delta, gamma, and vega limits.

## Configuration

### config.toml

```toml
[risk.greeks]
max_portfolio_delta = 500.0
max_portfolio_gamma = 100.0
max_daily_theta = -200.0
max_portfolio_vega = 1000.0
greeks_refresh_interval_seconds = 30
```

### GreeksRiskConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_portfolio_delta` | `float \| None` | `None` | Max absolute portfolio delta |
| `max_portfolio_gamma` | `float \| None` | `None` | Max absolute portfolio gamma |
| `max_daily_theta` | `float \| None` | `None` | Max daily theta (negative) |
| `max_portfolio_vega` | `float \| None` | `None` | Max absolute portfolio vega |
| `max_position_delta` | `float \| None` | `None` | Max per-position delta |
| `max_position_gamma` | `float \| None` | `None` | Max per-position gamma |
| `max_position_vega` | `float \| None` | `None` | Max per-position vega |
| `greeks_refresh_interval_seconds` | `float` | `30.0` | Cache refresh interval |

All greeks checks are optional — if a limit is `None`, the check passes automatically.

## Dashboard

The dashboard displays:
- **Portfolio greeks summary**: Total delta, gamma, theta, vega in the Greeks panel
- **Per-position greeks**: Delta, gamma, theta, vega columns on options positions
- **Risk violations**: Greeks limit breaches appear in the risk violation log
