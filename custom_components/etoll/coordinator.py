"""DataUpdateCoordinator for the NSW E-Toll integration.

Owns the long-lived `EtollClient`, performs polling, and produces the data
structure consumed by sensor/binary_sensor platforms.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    AccountSummary,
    ActivityEntry,
    EtollAuthError,
    EtollClient,
    EtollError,
    compute_yearly_rebate,
    latest_toll,
    sum_tolls,
    week_bounds,
    year_bounds,
)
from .const import (
    CONF_ACCOUNT_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_WEEKLY_CAP,
    CONF_WEEKLY_UPPER_CAP,
    CONF_YEARLY_REBATE_CAP,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_WEEKLY_CAP_AUD,
    DEFAULT_WEEKLY_UPPER_CAP_AUD,
    DEFAULT_YEARLY_REBATE_CAP_AUD,
    DOMAIN,
    INITIAL_FETCH_MAX_PAGES,
    RECENT_ACTIVITY_PAGE_SIZE,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class EtollData:
    """Snapshot returned by the coordinator on every refresh."""

    account: AccountSummary
    activity: list[ActivityEntry]   # newest first
    weekly_spend: float
    yearly_spend: float
    weekly_cap: float
    weekly_upper_cap: float
    weekly_excess: float
    weekly_claimable: float
    rebate_eligible: bool
    yearly_rebate_cap: float
    yearly_accrued_rebate: float
    yearly_rebate_remaining: float
    last_toll: ActivityEntry | None
    weekly_trip_count: int
    yearly_trip_count: int
    refreshed_at: datetime
    tags: dict[int, "EtollTagData"]   # per-tag snapshots keyed by tag_serial


@dataclass
class EtollTagData:
    """Per-tag snapshot produced alongside EtollData on every refresh."""

    tag_serial: int
    activity: list[ActivityEntry]   # toll entries for this tag only, newest first
    weekly_spend: float
    yearly_spend: float
    weekly_cap: float
    weekly_upper_cap: float
    weekly_excess: float
    weekly_claimable: float
    rebate_eligible: bool
    yearly_rebate_cap: float
    yearly_accrued_rebate: float
    yearly_rebate_remaining: float
    last_toll: ActivityEntry | None
    weekly_trip_count: int
    yearly_trip_count: int
    refreshed_at: datetime


class EtollCoordinator(DataUpdateCoordinator[EtollData]):
    """Polls the NSW E-Toll API and exposes the derived state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES,
            entry.data.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.data[CONF_EMAIL]})",
            update_interval=timedelta(minutes=int(scan_interval)),
        )
        self._entry = entry
        self._account_id: int | None = entry.data.get(CONF_ACCOUNT_ID)
        # Use HA's shared aiohttp session — it pools connections and respects
        # HA's shutdown lifecycle.
        self._client = EtollClient(
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            session=async_get_clientsession(hass),
        )
        # Cache of "all activity ever seen" so we can compute YTD totals
        # without re-paging through the entire history every poll. Keyed by
        # codInvoicingEvent for dedup.
        self._activity_cache: dict[int, ActivityEntry] = {}
        self._first_run = True

    @property
    def account_id(self) -> int | None:
        return self._account_id

    @property
    def weekly_cap(self) -> float:
        return float(
            self._entry.options.get(
                CONF_WEEKLY_CAP,
                self._entry.data.get(CONF_WEEKLY_CAP, DEFAULT_WEEKLY_CAP_AUD),
            )
        )

    @property
    def weekly_upper_cap(self) -> float:
        return float(
            self._entry.options.get(
                CONF_WEEKLY_UPPER_CAP,
                self._entry.data.get(CONF_WEEKLY_UPPER_CAP, DEFAULT_WEEKLY_UPPER_CAP_AUD),
            )
        )

    @property
    def yearly_rebate_cap(self) -> float:
        return float(
            self._entry.options.get(
                CONF_YEARLY_REBATE_CAP,
                self._entry.data.get(CONF_YEARLY_REBATE_CAP, DEFAULT_YEARLY_REBATE_CAP_AUD),
            )
        )

    async def _async_update_data(self) -> EtollData:
        try:
            return await self._poll()
        except EtollAuthError as err:
            # Surface as auth failure so HA shows the "reconfigure" button.
            from homeassistant.exceptions import ConfigEntryAuthFailed

            raise ConfigEntryAuthFailed(str(err)) from err
        except EtollError as err:
            raise UpdateFailed(str(err)) from err

    async def _poll(self) -> EtollData:
        # Resolve which account to track. If none was pinned in the config
        # entry, take the first accessible one.
        if self._account_id is None:
            default_account = await self._client.get_default_account()
            self._account_id = default_account.cod_account
            _LOGGER.debug("Resolved default account %s", self._account_id)

        account = await self._client.get_account(self._account_id)

        # Compute year start before fetching so we can pass it to the searcher.
        now_for_fetch = datetime.now()
        ytd_start = datetime(now_for_fetch.year, 1, 1)

        if self._first_run:
            # Use the searcher endpoint for the initial YTD backfill. The
            # regular account-activity endpoint is limited to the current
            # quarter (~55 rows); the searcher accepts an explicit date
            # range and returns the full year's data.
            entries = await self._client.search_account_activity(
                self._account_id,
                start=ytd_start,
                end=now_for_fetch,
                page_size=RECENT_ACTIVITY_PAGE_SIZE,
                max_pages=INITIAL_FETCH_MAX_PAGES,
            )
            self._first_run = False
        else:
            # Fetch enough pages to cover everything posted since our newest
            # cached entry. `get_recent_activity` short-circuits as soon as it
            # crosses `since`.
            newest_cached = max(
                (e.posted_at for e in self._activity_cache.values() if e.posted_at),
                default=None,
            )
            entries = await self._client.get_recent_activity(
                self._account_id,
                since=newest_cached - timedelta(minutes=5) if newest_cached else None,
                max_pages=4,
                page_size=RECENT_ACTIVITY_PAGE_SIZE,
            )

        for entry in entries:
            self._activity_cache[entry.cod_invoicing_event] = entry

        all_activity = sorted(
            self._activity_cache.values(),
            key=lambda e: e.posted_at or datetime.min,
            reverse=True,
        )

        now = datetime.now()
        week_start, week_end = week_bounds(now)
        year_start, year_end = year_bounds(now)

        weekly_spend = sum_tolls(all_activity, week_start, week_end)
        yearly_spend = sum_tolls(all_activity, year_start, year_end)
        cap = self.weekly_cap
        upper_cap = self.weekly_upper_cap
        yearly_cap = self.yearly_rebate_cap
        excess = round(max(0.0, weekly_spend - cap), 2)
        claimable = round(min(excess, upper_cap - cap), 2)
        yearly_rebate = compute_yearly_rebate(
            all_activity, year_start, year_end,
            weekly_threshold=cap,
            weekly_upper_cap=upper_cap,
            yearly_rebate_cap=yearly_cap,
        )
        last = latest_toll(all_activity)

        tag_serials: set[int] = {
            e.tag_serial
            for e in all_activity
            if e.is_toll and e.tag_serial is not None
        }
        tags = {
            serial: self._compute_tag_data(
                serial, all_activity,
                week_start, week_end, year_start, year_end,
                cap, upper_cap, yearly_cap, now,
            )
            for serial in tag_serials
        }

        weekly_trip_count = sum(
            1
            for e in all_activity
            if e.is_toll
            and e.posted_at
            and week_start <= _naive(e.posted_at) < week_end
        )
        yearly_trip_count = sum(
            1
            for e in all_activity
            if e.is_toll
            and e.posted_at
            and year_start <= _naive(e.posted_at) < year_end
        )

        return EtollData(
            account=account,
            activity=all_activity,
            weekly_spend=weekly_spend,
            yearly_spend=yearly_spend,
            weekly_cap=cap,
            weekly_upper_cap=upper_cap,
            weekly_excess=excess,
            weekly_claimable=claimable,
            rebate_eligible=claimable > 0 and yearly_rebate < yearly_cap,
            yearly_rebate_cap=yearly_cap,
            yearly_accrued_rebate=yearly_rebate,
            yearly_rebate_remaining=round(max(0.0, yearly_cap - yearly_rebate), 2),
            last_toll=last,
            weekly_trip_count=weekly_trip_count,
            yearly_trip_count=yearly_trip_count,
            refreshed_at=now,
            tags=tags,
        )

    def _compute_tag_data(
        self,
        tag_serial: int,
        all_activity: list[ActivityEntry],
        week_start: datetime,
        week_end: datetime,
        year_start: datetime,
        year_end: datetime,
        cap: float,
        upper_cap: float,
        yearly_cap: float,
        now: datetime,
    ) -> EtollTagData:
        tag_activity = [e for e in all_activity if e.tag_serial == tag_serial]
        weekly_spend = sum_tolls(tag_activity, week_start, week_end)
        yearly_spend = sum_tolls(tag_activity, year_start, year_end)
        excess = round(max(0.0, weekly_spend - cap), 2)
        claimable = round(min(excess, upper_cap - cap), 2)
        yearly_rebate = compute_yearly_rebate(
            tag_activity, year_start, year_end,
            weekly_threshold=cap,
            weekly_upper_cap=upper_cap,
            yearly_rebate_cap=yearly_cap,
        )
        last = latest_toll(tag_activity)
        weekly_trips = sum(
            1 for e in tag_activity
            if e.is_toll and e.posted_at
            and week_start <= _naive(e.posted_at) < week_end
        )
        yearly_trips = sum(
            1 for e in tag_activity
            if e.is_toll and e.posted_at
            and year_start <= _naive(e.posted_at) < year_end
        )
        return EtollTagData(
            tag_serial=tag_serial,
            activity=tag_activity,
            weekly_spend=weekly_spend,
            yearly_spend=yearly_spend,
            weekly_cap=cap,
            weekly_upper_cap=upper_cap,
            weekly_excess=excess,
            weekly_claimable=claimable,
            rebate_eligible=claimable > 0 and yearly_rebate < yearly_cap,
            yearly_rebate_cap=yearly_cap,
            yearly_accrued_rebate=yearly_rebate,
            yearly_rebate_remaining=round(max(0.0, yearly_cap - yearly_rebate), 2),
            last_toll=last,
            weekly_trip_count=weekly_trips,
            yearly_trip_count=yearly_trips,
            refreshed_at=now,
        )

    async def async_close(self) -> None:
        await self._client.close()


def _naive(dt: datetime) -> datetime:
    return dt if dt.tzinfo is None else dt.replace(tzinfo=None)
