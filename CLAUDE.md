# ha-etoll — Agent Guide

This is a Home Assistant custom integration that polls the NSW E-Toll customer portal (`api.account.myetoll.transport.nsw.gov.au`) and exposes toll account data (balance, weekly/yearly spend, rebate eligibility) as HA sensors. The integration targets NSW Toll Relief — a NSW Government scheme that refunds toll spend above $60/week, capped at $5,000/year.

## Repository map

| Path | Purpose |
|---|---|
| `custom_components/etoll/client.py` | Pure async aiohttp client + all business-logic helpers. **Zero HA imports.** Safe to import and test in plain Python. |
| `custom_components/etoll/coordinator.py` | `DataUpdateCoordinator` subclass. Owns `EtollClient`, `_activity_cache` (dedup dict), and produces `EtollData` / `EtollTagData` snapshots every poll. |
| `custom_components/etoll/sensor.py` | 11 account-level sensors + 10 per-tag sensors. Per-tag entities are discovered dynamically via `coordinator.async_add_listener`. |
| `custom_components/etoll/binary_sensor.py` | Rebate-eligibility binary sensors (account-level + one per tag). Same dynamic discovery pattern as sensor.py. |
| `custom_components/etoll/config_flow.py` | HA config flow (setup) and options flow (reconfigure). |
| `custom_components/etoll/const.py` | All constants: rebate thresholds, polling defaults, config-entry keys, domain. |
| `examples/test_client.py` | Manual smoke test requiring real credentials. Not part of CI. |
| `tests/` | Unit and integration tests. Run with `make test`. |

## Commands

```bash
# One-time setup — create venv and install all dev dependencies
make venv
source .venv/bin/activate

# Run all CI gates (lint + typecheck + test)
make ci

# Individual gates
make lint        # ruff check + format check
make typecheck   # mypy on client.py and const.py
make test        # pytest with coverage

# Manual smoke test (requires real NSW E-Toll credentials)
ETOLL_EMAIL='your@email.com' ETOLL_PASSWORD='yourpassword' python examples/test_client.py
```

## Architecture decisions

**Currency scaling** — API values are integers scaled by 100,000. `4250000 → AUD 42.50`. Always use `_scale()` in `client.py` to convert; never divide manually.

**Week boundary** — NSW Toll Relief uses Mon–Sun weeks. `week_bounds()` defaults to `week_starts_on=0` (Monday). Do not change this default.

**Activity deduplication** — `EtollCoordinator._activity_cache` is a `dict[int, ActivityEntry]` keyed by `codInvoicingEvent`. Every poll *merges* new entries into the cache; it never replaces the whole dict. The latest version of a row wins (same key = overwrite).

**First-run vs incremental** — On the very first poll, the coordinator calls `search_account_activity` with a full YTD date range (up to 1,000 rows). On subsequent polls it calls `get_recent_activity` with `since = newest_cached_timestamp - 5 minutes`. The 5-minute lookback guards against clock skew.

**Tag discovery** — Per-tag sensor entities are created lazily when a tag serial first appears in activity data. This requires no reconfiguration when a new tag is added to the vehicle.

**Timestamps** — The API returns naive ISO strings in Sydney local time. `_parse_iso()` preserves naivety. `sensor.py`'s `_to_aware()` converts to tz-aware using the host's system timezone. Tests that assert on timestamps should use naive `datetime` objects.

## Agent gotchas

- **Do not add `homeassistant` imports to `client.py`.** It is intentionally dependency-free. The HA integration wraps it via the coordinator.
- **`sum_tolls()` uses `gross_amount`, not `signed_amount`.** `signed_amount` is negative for debits; `gross_amount` is always positive. Mixing them breaks rebate math silently.
- **Paging is not uniform.** `get_account_activity()` uses 1-based page numbers (portal convention). `search_account_activity()` uses 0-based pages (Spring Pageable). Do not conflate them.
- **`rebate_eligible` requires two conditions.** It is `claimable > 0 AND yearly_accrued_rebate < yearly_cap`. A week with high spend becomes ineligible once the yearly cap is exhausted.
- **`compute_yearly_rebate()` passes all entries**, not year-pre-filtered ones, into `sum_tolls()` for each week. This is intentional so weeks straddling the year boundary are computed correctly using their full week's data. Do not pre-filter entries before calling `compute_yearly_rebate()`.
- **`event_type == 0` only.** `sum_tolls()` and `latest_toll()` count only toll events (`EVENT_TYPE_TOLL = 0`). Payments (`3`) and fees (`1`) are excluded. If you change which types count as "tolls", update all three functions consistently.
- **`ActivityEntry.tag_serial`** comes directly from `numTagSerial` in the API response — it can be `None` for entries without a linked tag.

## Testing strategy

- **Pure function tests** (`tests/test_client_pure.py`) — no HA, no HTTP mocking. Just `from custom_components.etoll.client import ...` and assert. Covers all rebate math.
- **HTTP client tests** (`tests/test_client_http.py`) — mock aiohttp responses with `aioresponses`. Covers auth, retry, and paging logic.
- **Coordinator tests** (`tests/test_coordinator.py`) — mock `EtollClient` methods with `AsyncMock`. Covers first-run vs incremental, dedup, `EtollData` computation, and error propagation.
- **Sensor / binary sensor tests** (`tests/test_sensor.py`, `tests/test_binary_sensor.py`) — use `pytest-homeassistant-custom-component` fixtures. Covers entity state and attributes.

`pytest-homeassistant-custom-component` bundles HA core for testing. Its bundled `pytest-socket` plugin blocks real network calls — any test that accidentally hits the network will fail loudly.
