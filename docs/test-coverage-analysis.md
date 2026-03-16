# Test Coverage Analysis

_Generated 2026-03-16_

The codebase has **648 test methods** across 28 test files, providing solid coverage of core trading logic. However, several important areas are undertested or entirely untested. This document identifies the gaps ordered by impact, with concrete recommendations for each.

---

## Summary Table

| Area | Risk Level | Current State |
|---|---|---|
| `adapters/options/adapter.py` | **Critical** | Zero coverage |
| `data/serialization.py` | High | Zero coverage |
| `core/config.py` (`load_settings`) | High | Zero coverage |
| `core/order_router.py` — options methods | High | No tests for 6 methods |
| `strategy/context.py` — bracket/options paths | Medium | Not exercised via context |
| `risk/manager.py` — greeks integration | Medium | Integration tested, unit paths missing |
| `core/clock.py` | Low | Zero coverage |
| `core/logging.py` | Low | Zero coverage |
| `strategy/base.py` — price gate edge cases | Low | Basic cases covered |

---

## 1. `adapters/options/adapter.py` — `OptionsExecAdapter` (**Critical**)

**Status:** No test file exists. Zero coverage for the entire options execution adapter.

This is the highest-priority gap. `OptionsExecAdapter` handles real order submission for multi-leg strategies (spreads, condors, butterflies). A bug here has direct financial consequence.

**Methods with no tests:**
- `connect()` / `disconnect()` — lifecycle and background task cancellation
- `submit_option_order()` — single-leg order construction, SDK mapping, event publishing, rate-limit/API-error handling
- `submit_multileg_order()` — multi-leg order construction, UUID validation, leg mapping
- `cancel_option_order()` — cancellation and error event path
- `preflight_option_order()` — preflight request construction
- `get_option_chain()` / `get_option_expirations()` — chain data retrieval
- `sync_portfolio()` — position parsing, filtering non-option positions
- `_track_order()` — fill/cancel/reject event publishing on status updates

**Recommended tests (follow `test_crypto_adapter.py` as a template):**

```python
class TestOptionsAdapterConnect:
    async def test_connect_starts_portfolio_loop(self, adapter, mock_client): ...
    async def test_disconnect_cancels_portfolio_task(self, adapter, mock_client): ...

class TestSubmitOptionOrder:
    async def test_market_buy_call(self, adapter, mock_client, bus): ...
    async def test_limit_sell_put(self, adapter, mock_client): ...
    async def test_rate_limit_error_publishes_event(self, adapter, mock_client, bus): ...
    async def test_api_error_publishes_event(self, adapter, mock_client, bus): ...

class TestSubmitMultilegOrder:
    async def test_two_leg_spread(self, adapter, mock_client, bus): ...
    async def test_four_leg_condor(self, adapter, mock_client, bus): ...
    async def test_invalid_uuid_gets_replaced(self, adapter, mock_client): ...
    async def test_api_error_publishes_event(self, adapter, mock_client, bus): ...

class TestSyncPortfolio:
    async def test_filters_non_option_positions(self, adapter, mock_client, bus): ...
    async def test_empty_portfolio(self, adapter, mock_client): ...
    async def test_error_is_swallowed(self, adapter, mock_client): ...

class TestTrackOrder:
    async def test_filled_publishes_event(self, adapter, bus): ...
    async def test_rejected_publishes_event(self, adapter, bus): ...
    async def test_cancelled_publishes_event(self, adapter, bus): ...
```

---

## 2. `data/serialization.py` (High)

**Status:** No test file. The `Format` enum, `serialize()`, `deserialize()`, `detect_format()`, and `has_msgpack()` are completely untested.

This module is the content-negotiation layer used by all REST ingestion endpoints and the WebSocket bridge. A silent bug in format detection would cause data loss without any error.

**Recommended tests:**

```python
class TestSerializeDeserialize:
    def test_json_roundtrip(self): ...
    def test_msgpack_roundtrip(self): ...
    def test_msgpack_raises_without_package(self, monkeypatch): ...  # mock _HAS_MSGPACK = False
    def test_json_is_default(self): ...

class TestDetectFormat:
    def test_msgpack_content_type(self): ...
    def test_json_content_type(self): ...
    def test_none_defaults_to_json(self): ...
    def test_unknown_content_type_defaults_to_json(self): ...
    def test_partial_msgpack_string_matches(self): ...  # "application/x-msgpack; charset=utf-8"
```

---

## 3. `core/config.py` — `load_settings()` / `load_toml()` (High)

**Status:** No test file. The two public functions that load all platform configuration are untested. `test_uvloop.py` instantiates `Settings` but never tests config loading from files.

This is the entrypoint for all production configuration. A regression here could silently fall back to defaults (e.g., wrong risk limits, wrong API credentials field names).

**Recommended tests:**

```python
class TestLoadToml:
    def test_returns_empty_dict_for_missing_file(self, tmp_path): ...
    def test_loads_valid_toml(self, tmp_path): ...

class TestLoadSettings:
    def test_defaults_when_no_file(self): ...
    def test_loads_risk_section_from_toml(self, tmp_path): ...
    def test_loads_nested_risk_greeks(self, tmp_path): ...  # [risk.greeks]
    def test_loads_nested_options_expiration(self, tmp_path): ...  # [options.expiration]
    def test_env_var_overrides_toml(self, monkeypatch, tmp_path): ...
    def test_explicit_config_path(self, tmp_path): ...
```

The nested section handling (`risk_data.pop("greeks", {})`, `options_data.pop("expiration", {})`) is particularly fragile and should be validated with TOML fixtures.

---

## 4. `core/order_router.py` — Options-Specific Methods (High)

**Status:** `test_order_router.py` has good coverage of the equity/crypto routing, but six options-specific methods have no tests:

- `submit_multileg_order()` — delegates to the OPTION adapter
- `cancel_option_order()` — delegates to the OPTION adapter
- `get_option_positions()` — delegates to the OPTION adapter
- `preflight_option_order()` — delegates to the OPTION adapter
- `get_option_chain()` — delegates to the OPTION adapter
- `get_option_expirations()` — delegates to the OPTION adapter
- `_get_options_adapter()` error path — raises `ValueError` when no options adapter registered

All of these follow the same pattern as equity/crypto tests already in `test_order_router.py`.

**Recommended additions to `test_order_router.py`:**

```python
class TestOptionsRouting:
    def test_get_options_adapter_raises_when_missing(self, router): ...
    async def test_submit_multileg_routes_to_options_adapter(self, router, options_adapter): ...
    async def test_cancel_option_order(self, router, options_adapter): ...
    async def test_get_option_positions(self, router, options_adapter): ...
    async def test_preflight_option_order(self, router, options_adapter): ...
    async def test_get_option_chain(self, router, options_adapter): ...
    async def test_get_option_expirations(self, router, options_adapter): ...
```

---

## 5. `strategy/context.py` — Bracket and Options Submission Paths (Medium)

**Status:** `test_strategy.py` covers `submit_order()` and `cancel_order()` via `TestStrategyContext`. However, three methods are not tested through the context at all:

- `submit_bracket_order()` — the bracket manager path (tested on `BracketOrderManager` directly, but the context wrapper and its "no bracket manager" fallback are not covered)
- `cancel_bracket_order()` — same gap
- `submit_options_strategy()` — the `build_and_submit` wrapper path entirely untested
- `options_strategy_builder` property — not tested (both `None` case and live case)

**Recommended additions to `test_strategy.py`:**

```python
class TestStrategyContextBracket:
    async def test_submit_bracket_no_manager_returns_none(self, bus): ...
    async def test_submit_bracket_delegates_to_manager(self, bus, mock_bracket): ...
    async def test_cancel_bracket_no_manager_returns_false(self, bus): ...
    async def test_cancel_bracket_delegates(self, bus, mock_bracket): ...

class TestStrategyContextOptions:
    def test_options_builder_property_none(self, bus): ...
    def test_options_builder_property_set(self, bus, mock_builder): ...
    async def test_submit_options_strategy_no_builder(self, bus): ...
    async def test_submit_options_strategy_no_exec(self, bus): ...
    async def test_submit_options_strategy_delegates(self, bus, mock_builder, mock_exec): ...
```

---

## 6. `risk/manager.py` — Greeks Path in `pre_trade_check()` (Medium)

**Status:** `test_greeks_integration.py` tests the greeks checks at the function level and through `RiskManager.pre_trade_check()` (6 integration tests). However, the unit-level path of `_run_greeks_checks()` is tested only indirectly. The following specific behaviors have no coverage:

- Multiple sequential greeks checks where the _second_ one fails (short-circuit behavior across checks)
- Violation recording when a greeks check fails — the `RiskViolation` is appended and the bus event is published
- The `update_open_order_count()` method is not tested in `test_risk.py` despite being a public interface

**Recommended additions:**

```python
async def test_greeks_violation_appended_to_state(bus, risk_manager): ...
async def test_greeks_second_check_fails_short_circuits(bus, risk_manager): ...
def test_update_open_order_count(risk_manager): ...
```

---

## 7. `core/clock.py` and `core/logging.py` (Low)

**Status:** Both have zero tests. These are simple utility modules but are called on every event loop tick and in every component.

- `clock.now()` and `clock.now_ns()` — worth testing that they return UTC-aware datetimes and int timestamps respectively
- `setup_logging()` — smoke test that it doesn't raise with various log levels and formats
- `get_logger()` — returns a bound logger with the correct component name

These are low-complexity tests, but since every component imports these, any breakage would be catastrophic and silent.

---

## 8. `strategy/base.py` — Price Gate Edge Cases (Low)

**Status:** `test_strategy.py` covers basic skip behavior, but the following edge cases in `_should_evaluate()` are not explicitly tested:

- `min_price_change_percent` gate — only the absolute `min_price_change` gate is tested
- Both gates configured simultaneously — which one fires first
- `skip_rate_percent` property with zero evaluations (denominator guard)
- `on_order_update()` and `on_position_update()` default implementations (they are no-ops, but testing them ensures subclasses don't accidentally break the call chain)

---

## Prioritized Action Plan

| Priority | File to Create | Estimated Tests |
|---|---|---|
| 1 | `tests/test_options_adapter.py` | ~30 |
| 2 | `tests/test_serialization.py` | ~12 |
| 3 | `tests/test_config.py` | ~10 |
| 4 | Add to `tests/test_order_router.py` | ~8 |
| 5 | Add to `tests/test_strategy.py` | ~10 |
| 6 | Add to `tests/test_risk.py` | ~4 |
| 7 | `tests/test_clock.py` + `tests/test_logging.py` | ~6 |

The first three items represent entirely untested modules that could mask bugs silently. Items 4–7 extend existing test suites to close specific behavioral gaps.
