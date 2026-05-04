"""Constants for the NSW E-Toll integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "etoll"
MANUFACTURER = "Transport for NSW"
MODEL = "E-Toll Account"
MODEL_TAG = "E-Toll Tag"

# Config-entry keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_ACCOUNT_ID = "account_id"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_WEEKLY_CAP = "weekly_cap"

# Defaults
DEFAULT_SCAN_INTERVAL_MINUTES = 60
MIN_SCAN_INTERVAL_MINUTES = 15  # be a friendly citizen — NSW backend is shared

# NSW Toll Relief: tolls paid above this much per week become eligible for
# rebate. The cap is set by Transport for NSW; users can override it in
# Options if/when the scheme changes.
DEFAULT_WEEKLY_CAP_AUD = 60.0

# Toll spend above this weekly ceiling earns no additional rebate.
# The claimable rebate per week is min(max(0, spend - lower), upper - lower).
DEFAULT_WEEKLY_UPPER_CAP_AUD = 400.0
MAX_WEEKLY_REBATE_AUD = DEFAULT_WEEKLY_UPPER_CAP_AUD - DEFAULT_WEEKLY_CAP_AUD  # 340.0

# Maximum total rebate claimable across the whole scheme year.
DEFAULT_YEARLY_REBATE_CAP_AUD = 5000.0

CONF_WEEKLY_UPPER_CAP = "weekly_upper_cap"
CONF_YEARLY_REBATE_CAP = "yearly_rebate_cap"

# How many activity rows the coordinator pulls each refresh. Most users will
# have <50 rows per fortnight so 50 covers a whole week comfortably; the
# integration falls back to multi-page fetches at first start to populate
# year-to-date totals.
RECENT_ACTIVITY_PAGE_SIZE = 50
INITIAL_FETCH_MAX_PAGES = 20  # ~1000 rows = ~6-12 months for a daily commuter

# Coordinator update interval from minutes
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)

ATTRIBUTION = "Data provided by Transport for NSW E-Toll"
