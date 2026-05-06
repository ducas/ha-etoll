"""Tests for EtollCoordinator polling logic, deduplication, and data computation."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.etoll.client import EtollAuthError, EtollError
from custom_components.etoll.coordinator import EtollCoordinator
from tests.conftest import make_account, make_toll_entry


# ---------------------------------------------------------------------------
# Helpers to build a minimal coordinator with a mocked client
# ---------------------------------------------------------------------------


def _make_coordinator(mock_client, *, account_id: int | None = 1234567):
    """Build an EtollCoordinator with mocked HA dependencies."""
    hass = MagicMock()
    hass.data = {}
    hass.config = MagicMock()
    hass.config.time_zone = "Australia/Sydney"
    hass.bus = MagicMock()
    hass.bus.async_listen_once = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        "email": "test@example.com",
        "password": "secret",
        "account_id": account_id,
    }
    entry.options = {}

    coordinator = EtollCoordinator.__new__(EtollCoordinator)
    # Manually init state that __init__ would set, bypassing HA super().__init__
    coordinator.hass = hass
    coordinator._entry = entry
    coordinator._account_id = account_id
    coordinator._client = mock_client
    coordinator._activity_cache = {}
    coordinator._first_run = True
    coordinator.logger = MagicMock()
    coordinator.data = None
    coordinator.last_update_success = True
    coordinator._listeners = []
    coordinator._unsub_refresh = None
    coordinator.config_entry = entry
    coordinator.name = "etoll (test)"
    coordinator.update_interval = timedelta(minutes=60)
    return coordinator


# ---------------------------------------------------------------------------
# First-run behaviour
# ---------------------------------------------------------------------------


class TestFirstRun:
    async def test_first_run_uses_searcher_endpoint(self, mock_client):
        entries = [make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        await coordinator._poll()

        mock_client.search_account_activity.assert_called_once()
        mock_client.get_recent_activity.assert_not_called()

    async def test_first_run_sets_first_run_to_false(self, mock_client):
        coordinator = _make_coordinator(mock_client)
        assert coordinator._first_run is True

        await coordinator._poll()

        assert coordinator._first_run is False

    async def test_first_run_populates_cache(self, mock_client):
        entries = [
            make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6)),
            make_toll_entry(2, 1234567, 4.20, datetime(2026, 5, 7)),
        ]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        await coordinator._poll()

        assert len(coordinator._activity_cache) == 2
        assert 1 in coordinator._activity_cache
        assert 2 in coordinator._activity_cache


# ---------------------------------------------------------------------------
# Incremental polling
# ---------------------------------------------------------------------------


class TestIncrementalPoll:
    async def test_subsequent_poll_uses_get_recent_activity(self, mock_client):
        entries = [make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        # First run
        await coordinator._poll()
        mock_client.get_recent_activity = AsyncMock(return_value=[])

        # Second run
        await coordinator._poll()

        mock_client.get_recent_activity.assert_called_once()
        # search should not be called again
        assert mock_client.search_account_activity.call_count == 1

    async def test_incremental_uses_since_minus_five_minutes(self, mock_client):
        ts = datetime(2026, 5, 7, 8, 15, 0)
        entries = [make_toll_entry(1, 1234567, 6.30, ts)]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        await coordinator._poll()
        mock_client.get_recent_activity = AsyncMock(return_value=[])
        await coordinator._poll()

        call_kwargs = mock_client.get_recent_activity.call_args
        since = call_kwargs.kwargs.get("since") or call_kwargs[1].get("since")
        expected = ts - timedelta(minutes=5)
        assert since == expected

    async def test_new_entries_merged_into_cache(self, mock_client):
        entry1 = make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))
        mock_client.search_account_activity = AsyncMock(return_value=[entry1])
        coordinator = _make_coordinator(mock_client)
        await coordinator._poll()

        entry2 = make_toll_entry(2, 1234567, 4.20, datetime(2026, 5, 7))
        mock_client.get_recent_activity = AsyncMock(return_value=[entry2])
        await coordinator._poll()

        assert len(coordinator._activity_cache) == 2

    async def test_duplicate_entries_deduplicated(self, mock_client):
        entry = make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))
        updated_entry = make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))
        mock_client.search_account_activity = AsyncMock(return_value=[entry])
        coordinator = _make_coordinator(mock_client)
        await coordinator._poll()

        # Same key returned again on next poll — cache should not grow
        mock_client.get_recent_activity = AsyncMock(return_value=[updated_entry])
        await coordinator._poll()

        assert len(coordinator._activity_cache) == 1

    async def test_cache_not_replaced_on_second_poll(self, mock_client):
        entry1 = make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))
        mock_client.search_account_activity = AsyncMock(return_value=[entry1])
        coordinator = _make_coordinator(mock_client)
        await coordinator._poll()

        mock_client.get_recent_activity = AsyncMock(return_value=[])
        await coordinator._poll()

        # Old entry still in cache
        assert 1 in coordinator._activity_cache


# ---------------------------------------------------------------------------
# Account ID resolution
# ---------------------------------------------------------------------------


class TestAccountIdResolution:
    async def test_none_account_id_resolved_from_default(self, mock_client):
        account = make_account(cod_account=9999999)
        mock_client.get_default_account = AsyncMock(return_value=account)
        mock_client.get_account = AsyncMock(return_value=account)
        coordinator = _make_coordinator(mock_client, account_id=None)

        await coordinator._poll()

        mock_client.get_default_account.assert_called_once()
        assert coordinator._account_id == 9999999

    async def test_pinned_account_id_skips_default_lookup(self, mock_client):
        coordinator = _make_coordinator(mock_client, account_id=1234567)

        await coordinator._poll()

        mock_client.get_default_account.assert_not_called()


# ---------------------------------------------------------------------------
# EtollData computation
# ---------------------------------------------------------------------------


class TestEtollDataComputation:
    async def test_weekly_spend_and_excess(self, mock_client):
        # This week: $70 spend → $10 excess over $60 cap
        monday = datetime(2026, 5, 4)
        entries = [make_toll_entry(1, 1234567, 70.00, monday + timedelta(days=1))]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        with patch("custom_components.etoll.coordinator.datetime") as mock_dt:
            mock_dt.now.return_value = monday + timedelta(days=2)
            mock_dt.min = datetime.min
            mock_dt.combine = datetime.combine
            result = await coordinator._poll()

        assert result.weekly_spend == 70.00
        assert result.weekly_excess == 10.00
        assert result.weekly_claimable == 10.00

    async def test_rebate_eligible_true_when_claimable_positive(self, mock_client):
        monday = datetime(2026, 5, 4)
        entries = [make_toll_entry(1, 1234567, 70.00, monday + timedelta(days=1))]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        with patch("custom_components.etoll.coordinator.datetime") as mock_dt:
            mock_dt.now.return_value = monday + timedelta(days=2)
            mock_dt.min = datetime.min
            mock_dt.combine = datetime.combine
            result = await coordinator._poll()

        assert result.rebate_eligible is True

    async def test_rebate_eligible_false_when_yearly_cap_exhausted(self, mock_client):
        # Build enough YTD spend to exhaust the $5000 yearly cap
        entries = [
            make_toll_entry(
                i, 1234567, 400.00,
                datetime(2026, 1, 5) + timedelta(weeks=i),
            )
            for i in range(20)
        ]
        # Add a current-week entry that would normally be eligible
        entries.append(make_toll_entry(99, 1234567, 70.00, datetime(2026, 5, 6)))

        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        with patch("custom_components.etoll.coordinator.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 7)
            mock_dt.min = datetime.min
            mock_dt.combine = datetime.combine
            result = await coordinator._poll()

        # Yearly cap should be exhausted → not eligible
        assert result.yearly_accrued_rebate == 5000.00
        assert result.rebate_eligible is False

    async def test_tags_dict_populated_from_activity(self, mock_client):
        entries = [
            make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6), tag_serial=98765),
        ]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        with patch("custom_components.etoll.coordinator.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 7)
            mock_dt.min = datetime.min
            mock_dt.combine = datetime.combine
            result = await coordinator._poll()

        assert 98765 in result.tags

    async def test_tags_empty_when_no_tag_serials(self, mock_client):
        entries = [
            make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6), tag_serial=None),
        ]
        mock_client.search_account_activity = AsyncMock(return_value=entries)
        coordinator = _make_coordinator(mock_client)

        with patch("custom_components.etoll.coordinator.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 7)
            mock_dt.min = datetime.min
            mock_dt.combine = datetime.combine
            result = await coordinator._poll()

        assert result.tags == {}


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    async def test_etoll_auth_error_raises_config_entry_auth_failed(self, mock_client):
        mock_client.get_account = AsyncMock(side_effect=EtollAuthError("bad creds"))
        coordinator = _make_coordinator(mock_client)
        coordinator._first_run = False
        coordinator._activity_cache = {
            1: make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))
        }

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    async def test_etoll_error_raises_update_failed(self, mock_client):
        mock_client.get_account = AsyncMock(side_effect=EtollError("API down"))
        coordinator = _make_coordinator(mock_client)
        coordinator._first_run = False
        coordinator._activity_cache = {
            1: make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 6))
        }

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
