"""Tests for binary sensor entities."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from custom_components.etoll.binary_sensor import (
    EtollTagRebateEligibleBinarySensor,
    RebateEligibleBinarySensor,
)
from custom_components.etoll.coordinator import EtollData, EtollTagData
from tests.conftest import make_account


def _make_etoll_data(
    *,
    rebate_eligible: bool = True,
    weekly_spend: float = 70.0,
    weekly_cap: float = 60.0,
    weekly_excess: float = 10.0,
    weekly_claimable: float = 10.0,
    yearly_accrued_rebate: float = 10.0,
    yearly_rebate_cap: float = 5000.0,
    weekly_trip_count: int = 5,
    tags: dict | None = None,
) -> EtollData:
    return EtollData(
        account=make_account(),
        activity=[],
        weekly_spend=weekly_spend,
        yearly_spend=weekly_spend,
        weekly_cap=weekly_cap,
        weekly_upper_cap=400.0,
        weekly_excess=weekly_excess,
        weekly_claimable=weekly_claimable,
        rebate_eligible=rebate_eligible,
        yearly_rebate_cap=yearly_rebate_cap,
        yearly_accrued_rebate=yearly_accrued_rebate,
        yearly_rebate_remaining=round(yearly_rebate_cap - yearly_accrued_rebate, 2),
        last_toll=None,
        weekly_trip_count=weekly_trip_count,
        yearly_trip_count=weekly_trip_count,
        refreshed_at=datetime(2026, 5, 7),
        tags=tags or {},
    )


def _make_tag_data(
    tag_serial: int = 98765,
    *,
    rebate_eligible: bool = True,
    weekly_spend: float = 70.0,
    weekly_cap: float = 60.0,
    weekly_excess: float = 10.0,
    weekly_trip_count: int = 3,
) -> EtollTagData:
    return EtollTagData(
        tag_serial=tag_serial,
        activity=[],
        weekly_spend=weekly_spend,
        yearly_spend=weekly_spend,
        weekly_cap=weekly_cap,
        weekly_upper_cap=400.0,
        weekly_excess=weekly_excess,
        weekly_claimable=weekly_excess,
        rebate_eligible=rebate_eligible,
        yearly_rebate_cap=5000.0,
        yearly_accrued_rebate=weekly_excess,
        yearly_rebate_remaining=5000.0 - weekly_excess,
        last_toll=None,
        weekly_trip_count=weekly_trip_count,
        yearly_trip_count=weekly_trip_count,
        refreshed_at=datetime(2026, 5, 7),
    )


def _make_coordinator(data: EtollData | None = None, account_id: int = 1234567) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.account_id = account_id
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


def _make_entry(entry_id: str = "test_entry") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


# ---------------------------------------------------------------------------
# RebateEligibleBinarySensor
# ---------------------------------------------------------------------------


class TestRebateEligibleBinarySensor:
    def test_is_on_true_when_eligible(self):
        data = _make_etoll_data(rebate_eligible=True)
        coordinator = _make_coordinator(data)
        sensor = RebateEligibleBinarySensor.__new__(RebateEligibleBinarySensor)
        sensor.coordinator = coordinator
        sensor._attr_unique_id = "test_rebate_eligible"
        sensor._attr_device_info = {}

        assert sensor.is_on is True

    def test_is_on_false_when_not_eligible(self):
        data = _make_etoll_data(rebate_eligible=False)
        coordinator = _make_coordinator(data)
        sensor = RebateEligibleBinarySensor.__new__(RebateEligibleBinarySensor)
        sensor.coordinator = coordinator

        assert sensor.is_on is False

    def test_is_on_none_when_no_data(self):
        coordinator = _make_coordinator(None)
        sensor = RebateEligibleBinarySensor.__new__(RebateEligibleBinarySensor)
        sensor.coordinator = coordinator

        assert sensor.is_on is None

    def test_extra_state_attributes(self):
        data = _make_etoll_data(
            weekly_spend=70.0,
            weekly_cap=60.0,
            weekly_excess=10.0,
            weekly_trip_count=5,
        )
        coordinator = _make_coordinator(data)
        sensor = RebateEligibleBinarySensor.__new__(RebateEligibleBinarySensor)
        sensor.coordinator = coordinator

        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["weekly_spend_aud"] == 70.0
        assert attrs["weekly_cap_aud"] == 60.0
        assert attrs["weekly_excess_aud"] == 10.0
        assert attrs["trip_count_this_week"] == 5

    def test_extra_state_attributes_none_when_no_data(self):
        coordinator = _make_coordinator(None)
        sensor = RebateEligibleBinarySensor.__new__(RebateEligibleBinarySensor)
        sensor.coordinator = coordinator

        assert sensor.extra_state_attributes is None


# ---------------------------------------------------------------------------
# EtollTagRebateEligibleBinarySensor
# ---------------------------------------------------------------------------


class TestEtollTagRebateEligibleBinarySensor:
    def test_is_on_true_for_eligible_tag(self):
        tag_data = _make_tag_data(rebate_eligible=True)
        data = _make_etoll_data(tags={98765: tag_data})
        coordinator = _make_coordinator(data)
        sensor = EtollTagRebateEligibleBinarySensor.__new__(EtollTagRebateEligibleBinarySensor)
        sensor.coordinator = coordinator
        sensor._tag_serial = 98765

        assert sensor.is_on is True

    def test_is_on_false_for_ineligible_tag(self):
        tag_data = _make_tag_data(rebate_eligible=False)
        data = _make_etoll_data(tags={98765: tag_data})
        coordinator = _make_coordinator(data)
        sensor = EtollTagRebateEligibleBinarySensor.__new__(EtollTagRebateEligibleBinarySensor)
        sensor.coordinator = coordinator
        sensor._tag_serial = 98765

        assert sensor.is_on is False

    def test_is_on_none_when_tag_not_in_data(self):
        data = _make_etoll_data(tags={})  # tag serial not present
        coordinator = _make_coordinator(data)
        sensor = EtollTagRebateEligibleBinarySensor.__new__(EtollTagRebateEligibleBinarySensor)
        sensor.coordinator = coordinator
        sensor._tag_serial = 98765

        assert sensor.is_on is None

    def test_is_on_none_when_no_coordinator_data(self):
        coordinator = _make_coordinator(None)
        sensor = EtollTagRebateEligibleBinarySensor.__new__(EtollTagRebateEligibleBinarySensor)
        sensor.coordinator = coordinator
        sensor._tag_serial = 98765

        assert sensor.is_on is None

    def test_extra_state_attributes_for_tag(self):
        tag_data = _make_tag_data(
            weekly_spend=70.0,
            weekly_cap=60.0,
            weekly_excess=10.0,
            weekly_trip_count=3,
        )
        data = _make_etoll_data(tags={98765: tag_data})
        coordinator = _make_coordinator(data)
        sensor = EtollTagRebateEligibleBinarySensor.__new__(EtollTagRebateEligibleBinarySensor)
        sensor.coordinator = coordinator
        sensor._tag_serial = 98765

        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["weekly_spend_aud"] == 70.0
        assert attrs["weekly_cap_aud"] == 60.0
        assert attrs["weekly_excess_aud"] == 10.0
        assert attrs["trip_count_this_week"] == 3

    def test_extra_state_attributes_none_when_tag_missing(self):
        data = _make_etoll_data(tags={})
        coordinator = _make_coordinator(data)
        sensor = EtollTagRebateEligibleBinarySensor.__new__(EtollTagRebateEligibleBinarySensor)
        sensor.coordinator = coordinator
        sensor._tag_serial = 98765

        assert sensor.extra_state_attributes is None
