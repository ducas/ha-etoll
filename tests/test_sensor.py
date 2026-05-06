"""Tests for sensor entity values and attributes."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from custom_components.etoll.coordinator import EtollData, EtollTagData
from custom_components.etoll.sensor import (
    SENSORS,
    TAG_SENSORS,
    EtollSensor,
    EtollTagSensor,
)
from tests.conftest import make_account, make_toll_entry


def _make_etoll_data(  # noqa: PLR0913
    *,
    balance: float = 42.50,
    weekly_spend: float = 70.0,
    yearly_spend: float = 500.0,
    weekly_cap: float = 60.0,
    weekly_upper_cap: float = 400.0,
    weekly_excess: float = 10.0,
    weekly_claimable: float = 10.0,
    rebate_eligible: bool = True,
    yearly_accrued_rebate: float = 100.0,
    yearly_rebate_cap: float = 5000.0,
    weekly_trip_count: int = 5,
    yearly_trip_count: int = 42,
    last_toll=None,
    tags: dict | None = None,
) -> EtollData:
    account = make_account(balance=balance)
    return EtollData(
        account=account,
        activity=[],
        weekly_spend=weekly_spend,
        yearly_spend=yearly_spend,
        weekly_cap=weekly_cap,
        weekly_upper_cap=weekly_upper_cap,
        weekly_excess=weekly_excess,
        weekly_claimable=weekly_claimable,
        rebate_eligible=rebate_eligible,
        yearly_rebate_cap=yearly_rebate_cap,
        yearly_accrued_rebate=yearly_accrued_rebate,
        yearly_rebate_remaining=round(yearly_rebate_cap - yearly_accrued_rebate, 2),
        last_toll=last_toll,
        weekly_trip_count=weekly_trip_count,
        yearly_trip_count=yearly_trip_count,
        refreshed_at=datetime(2026, 5, 7),
        tags=tags or {},
    )


def _make_tag_data(tag_serial: int = 98765, **kwargs) -> EtollTagData:
    defaults = {
        "weekly_spend": 40.0,
        "yearly_spend": 200.0,
        "weekly_cap": 60.0,
        "weekly_upper_cap": 400.0,
        "weekly_excess": 0.0,
        "weekly_claimable": 0.0,
        "rebate_eligible": False,
        "yearly_rebate_cap": 5000.0,
        "yearly_accrued_rebate": 0.0,
        "yearly_rebate_remaining": 5000.0,
        "last_toll": None,
        "weekly_trip_count": 3,
        "yearly_trip_count": 20,
    }
    defaults.update(kwargs)
    return EtollTagData(
        tag_serial=tag_serial,
        activity=[],
        refreshed_at=datetime(2026, 5, 7),
        **defaults,
    )


def _make_coordinator(data: EtollData | None = None, account_id: int = 1234567) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.account_id = account_id
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


def _make_sensor(description, data: EtollData | None = None) -> EtollSensor:
    coordinator = _make_coordinator(data)
    sensor = EtollSensor.__new__(EtollSensor)
    sensor.coordinator = coordinator
    sensor.entity_description = description
    sensor._attr_unique_id = f"test_{description.key}"
    sensor._attr_device_info = {}
    return sensor


def _get_sensor_desc(key: str):
    for d in SENSORS:
        if d.key == key:
            return d
    raise KeyError(f"No sensor with key {key!r}")


def _get_tag_sensor_desc(key: str):
    for d in TAG_SENSORS:
        if d.key == key:
            return d
    raise KeyError(f"No tag sensor with key {key!r}")


# ---------------------------------------------------------------------------
# Account-level sensors
# ---------------------------------------------------------------------------


class TestEtollSensor:
    def test_balance_value(self):
        data = _make_etoll_data(balance=42.50)
        sensor = _make_sensor(_get_sensor_desc("balance"), data)
        assert sensor.native_value == 42.50

    def test_balance_attributes(self):
        data = _make_etoll_data(balance=42.50)
        sensor = _make_sensor(_get_sensor_desc("balance"), data)
        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["account_id"] == 1234567
        assert attrs["low_balance_threshold_aud"] == 10.0
        assert attrs["top_up_amount_aud"] == 50.0

    def test_weekly_spend_value(self):
        data = _make_etoll_data(weekly_spend=70.0)
        sensor = _make_sensor(_get_sensor_desc("weekly_spend"), data)
        assert sensor.native_value == 70.0

    def test_weekly_spend_attributes(self):
        data = _make_etoll_data(
            weekly_spend=70.0,
            weekly_cap=60.0,
            weekly_excess=10.0,
            weekly_claimable=10.0,
            weekly_trip_count=5,
        )
        sensor = _make_sensor(_get_sensor_desc("weekly_spend"), data)
        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["weekly_cap_aud"] == 60.0
        assert attrs["trip_count"] == 5
        assert attrs["rebate_eligible"] is True

    def test_weekly_excess_value(self):
        data = _make_etoll_data(weekly_excess=10.0)
        sensor = _make_sensor(_get_sensor_desc("weekly_excess"), data)
        assert sensor.native_value == 10.0

    def test_yearly_accrued_rebate_value(self):
        data = _make_etoll_data(yearly_accrued_rebate=350.0)
        sensor = _make_sensor(_get_sensor_desc("yearly_accrued_rebate"), data)
        assert sensor.native_value == 350.0

    def test_yearly_rebate_remaining_value(self):
        data = _make_etoll_data(yearly_accrued_rebate=350.0, yearly_rebate_cap=5000.0)
        sensor = _make_sensor(_get_sensor_desc("yearly_rebate_remaining"), data)
        assert sensor.native_value == 4650.0

    def test_trips_this_week_value(self):
        data = _make_etoll_data(weekly_trip_count=5)
        sensor = _make_sensor(_get_sensor_desc("trips_this_week"), data)
        assert sensor.native_value == 5

    def test_trips_this_year_value(self):
        data = _make_etoll_data(yearly_trip_count=42)
        sensor = _make_sensor(_get_sensor_desc("trips_this_year"), data)
        assert sensor.native_value == 42

    def test_last_trip_amount_none_when_no_toll(self):
        data = _make_etoll_data(last_toll=None)
        sensor = _make_sensor(_get_sensor_desc("last_trip_amount"), data)
        assert sensor.native_value is None

    def test_last_trip_amount_returns_gross_amount(self):
        toll = make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 7))
        data = _make_etoll_data(last_toll=toll)
        sensor = _make_sensor(_get_sensor_desc("last_trip_amount"), data)
        assert sensor.native_value == 6.30

    def test_last_trip_at_none_when_no_toll(self):
        data = _make_etoll_data(last_toll=None)
        sensor = _make_sensor(_get_sensor_desc("last_trip_at"), data)
        assert sensor.native_value is None

    def test_last_trip_at_returns_aware_datetime(self):
        toll = make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 7, 8, 15, 0))
        data = _make_etoll_data(last_toll=toll)
        sensor = _make_sensor(_get_sensor_desc("last_trip_at"), data)
        value = sensor.native_value
        assert value is not None
        assert value.tzinfo is not None  # _to_aware should have applied

    def test_all_sensors_return_none_when_no_data(self):
        for desc in SENSORS:
            sensor = _make_sensor(desc, None)
            assert sensor.native_value is None, (  # noqa: E501
                f"Sensor {desc.key} should return None when data is None"
            )


# ---------------------------------------------------------------------------
# Per-tag sensors
# ---------------------------------------------------------------------------


class TestEtollTagSensor:
    def _make_tag_sensor(self, key: str, tag_data: EtollTagData | None, tag_serial: int = 98765):
        desc = _get_tag_sensor_desc(key)
        if tag_data is not None:
            data = _make_etoll_data(tags={tag_serial: tag_data})
        else:
            data = _make_etoll_data(tags={})
        coordinator = _make_coordinator(data)
        sensor = EtollTagSensor.__new__(EtollTagSensor)
        sensor.coordinator = coordinator
        sensor.entity_description = desc
        sensor._tag_serial = tag_serial
        sensor._attr_unique_id = f"test_tag_{tag_serial}_{key}"
        sensor._attr_device_info = {}
        return sensor

    def test_weekly_spend_for_tag(self):
        tag = _make_tag_data(weekly_spend=40.0)
        sensor = self._make_tag_sensor("weekly_spend", tag)
        assert sensor.native_value == 40.0

    def test_returns_none_when_tag_not_in_data(self):
        sensor = self._make_tag_sensor("weekly_spend", None)
        assert sensor.native_value is None

    def test_returns_none_when_no_coordinator_data(self):
        desc = _get_tag_sensor_desc("weekly_spend")
        coordinator = _make_coordinator(None)
        sensor = EtollTagSensor.__new__(EtollTagSensor)
        sensor.coordinator = coordinator
        sensor.entity_description = desc
        sensor._tag_serial = 98765
        assert sensor.native_value is None

    def test_last_trip_amount_none_when_no_toll(self):
        tag = _make_tag_data(last_toll=None)
        sensor = self._make_tag_sensor("last_trip_amount", tag)
        assert sensor.native_value is None

    def test_last_trip_amount_returns_gross_amount(self):
        toll = make_toll_entry(1, 1234567, 6.30, datetime(2026, 5, 7), tag_serial=98765)
        tag = _make_tag_data(last_toll=toll)
        sensor = self._make_tag_sensor("last_trip_amount", tag)
        assert sensor.native_value == 6.30

    def test_all_tag_sensors_return_none_when_tag_missing(self):
        for desc in TAG_SENSORS:
            data = _make_etoll_data(tags={})
            coordinator = _make_coordinator(data)
            sensor = EtollTagSensor.__new__(EtollTagSensor)
            sensor.coordinator = coordinator
            sensor.entity_description = desc
            sensor._tag_serial = 98765
            assert sensor.native_value is None, (
                f"Tag sensor {desc.key} should return None when tag is missing"
            )
