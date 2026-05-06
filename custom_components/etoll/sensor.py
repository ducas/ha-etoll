"""Sensor platform for the NSW E-Toll integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL, MODEL_TAG
from .coordinator import EtollCoordinator, EtollData, EtollTagData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class EtollSensorDescription(SensorEntityDescription):
    """Describes an eToll sensor."""

    value_fn: Callable[[EtollData], Any]
    attributes_fn: Callable[[EtollData], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class EtollTagSensorDescription(SensorEntityDescription):
    """Describes a per-tag eToll sensor."""

    value_fn: Callable[[EtollTagData], Any]
    attributes_fn: Callable[[EtollTagData], dict[str, Any]] | None = None


def _last_toll_attrs(data: EtollData) -> dict[str, Any]:
    if data.last_toll is None:
        return {}
    t = data.last_toll
    return {
        "concession": t.concession_label or t.concession,
        "plaza": t.plaza_description or t.plaza_name,
        "vehicle_class": t.vehicle_class,
        "tag_serial": t.tag_serial,
        "amount_aud": t.gross_amount,
        "occurred_at": t.occurred_at.isoformat() if t.occurred_at else None,
        "posted_at": t.posted_at.isoformat() if t.posted_at else None,
    }


def _weekly_attrs(data: EtollData) -> dict[str, Any]:
    return {
        "weekly_cap_aud": data.weekly_cap,
        "weekly_upper_cap_aud": data.weekly_upper_cap,
        "weekly_excess_aud": data.weekly_excess,
        "weekly_claimable_aud": data.weekly_claimable,
        "trip_count": data.weekly_trip_count,
        "rebate_eligible": data.rebate_eligible,
    }


def _yearly_rebate_attrs(data: EtollData) -> dict[str, Any]:
    return {
        "yearly_rebate_cap_aud": data.yearly_rebate_cap,
        "yearly_accrued_rebate_aud": data.yearly_accrued_rebate,
        "yearly_rebate_remaining_aud": data.yearly_rebate_remaining,
    }


def _yearly_attrs(data: EtollData) -> dict[str, Any]:
    return {
        "trip_count": data.yearly_trip_count,
    }


def _balance_attrs(data: EtollData) -> dict[str, Any]:
    acc = data.account
    return {
        "low_balance_threshold_aud": acc.low_balance_threshold,
        "top_up_amount_aud": acc.top_up_amount,
        "last_balance_update": acc.last_balance_update.isoformat()
        if acc.last_balance_update
        else None,
        "account_id": acc.cod_account,
    }


def _tag_last_toll_attrs(data: EtollTagData) -> dict[str, Any]:
    if data.last_toll is None:
        return {}
    t = data.last_toll
    return {
        "concession": t.concession_label or t.concession,
        "plaza": t.plaza_description or t.plaza_name,
        "vehicle_class": t.vehicle_class,
        "tag_serial": t.tag_serial,
        "amount_aud": t.gross_amount,
        "occurred_at": t.occurred_at.isoformat() if t.occurred_at else None,
        "posted_at": t.posted_at.isoformat() if t.posted_at else None,
    }


def _tag_weekly_attrs(data: EtollTagData) -> dict[str, Any]:
    return {
        "weekly_cap_aud": data.weekly_cap,
        "weekly_upper_cap_aud": data.weekly_upper_cap,
        "weekly_excess_aud": data.weekly_excess,
        "weekly_claimable_aud": data.weekly_claimable,
        "trip_count": data.weekly_trip_count,
        "rebate_eligible": data.rebate_eligible,
    }


def _tag_yearly_rebate_attrs(data: EtollTagData) -> dict[str, Any]:
    return {
        "yearly_rebate_cap_aud": data.yearly_rebate_cap,
        "yearly_accrued_rebate_aud": data.yearly_accrued_rebate,
        "yearly_rebate_remaining_aud": data.yearly_rebate_remaining,
    }


def _tag_yearly_attrs(data: EtollTagData) -> dict[str, Any]:
    return {"trip_count": data.yearly_trip_count}


TAG_SENSORS: tuple[EtollTagSensorDescription, ...] = (
    EtollTagSensorDescription(
        key="weekly_spend",
        translation_key="weekly_spend",
        name="Toll spend this week",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.weekly_spend,
        attributes_fn=_tag_weekly_attrs,
    ),
    EtollTagSensorDescription(
        key="weekly_excess",
        translation_key="weekly_excess",
        name="Weekly cap excess",
        icon="mdi:cash-refund",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.weekly_excess,
    ),
    EtollTagSensorDescription(
        key="weekly_claimable_rebate",
        translation_key="weekly_claimable_rebate",
        name="Weekly claimable rebate",
        icon="mdi:cash-check",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.weekly_claimable,
        attributes_fn=_tag_weekly_attrs,
    ),
    EtollTagSensorDescription(
        key="yearly_accrued_rebate",
        translation_key="yearly_accrued_rebate",
        name="Yearly accrued rebate",
        icon="mdi:cash-plus",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.yearly_accrued_rebate,
        attributes_fn=_tag_yearly_rebate_attrs,
    ),
    EtollTagSensorDescription(
        key="yearly_rebate_remaining",
        translation_key="yearly_rebate_remaining",
        name="Yearly rebate remaining",
        icon="mdi:cash-minus",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.yearly_rebate_remaining,
        attributes_fn=_tag_yearly_rebate_attrs,
    ),
    EtollTagSensorDescription(
        key="yearly_spend",
        translation_key="yearly_spend",
        name="Toll spend this year",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.yearly_spend,
        attributes_fn=_tag_yearly_attrs,
    ),
    EtollTagSensorDescription(
        key="trips_this_week",
        translation_key="trips_this_week",
        name="Trips this week",
        icon="mdi:car-clock",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: d.weekly_trip_count,
    ),
    EtollTagSensorDescription(
        key="trips_this_year",
        translation_key="trips_this_year",
        name="Trips this year",
        icon="mdi:car-multiple",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.yearly_trip_count,
    ),
    EtollTagSensorDescription(
        key="last_trip_amount",
        translation_key="last_trip_amount",
        name="Last trip amount",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.last_toll.gross_amount if d.last_toll else None,
        attributes_fn=_tag_last_toll_attrs,
    ),
    EtollTagSensorDescription(
        key="last_trip_at",
        translation_key="last_trip_at",
        name="Last trip at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _to_aware(d.last_toll.posted_at) if d.last_toll else None,
        attributes_fn=_tag_last_toll_attrs,
    ),
)


SENSORS: tuple[EtollSensorDescription, ...] = (
    EtollSensorDescription(
        key="balance",
        translation_key="balance",
        name="Account balance",
        device_class=SensorDeviceClass.MONETARY,
        # Balance is a snapshot of present-time account state; it can go up
        # (top-ups) and down (tolls/fees), so MEASUREMENT is the right class.
        # TOTAL is reserved for cumulative sums that pair with a last_reset.
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.account.balance,
        attributes_fn=_balance_attrs,
    ),
    EtollSensorDescription(
        key="weekly_spend",
        translation_key="weekly_spend",
        name="Toll spend this week",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.weekly_spend,
        attributes_fn=_weekly_attrs,
    ),
    EtollSensorDescription(
        key="weekly_excess",
        translation_key="weekly_excess",
        name="Weekly cap excess",
        icon="mdi:cash-refund",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.weekly_excess,
    ),
    EtollSensorDescription(
        key="weekly_claimable_rebate",
        translation_key="weekly_claimable_rebate",
        name="Weekly claimable rebate",
        icon="mdi:cash-check",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.weekly_claimable,
        attributes_fn=_weekly_attrs,
    ),
    EtollSensorDescription(
        key="yearly_accrued_rebate",
        translation_key="yearly_accrued_rebate",
        name="Yearly accrued rebate",
        icon="mdi:cash-plus",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.yearly_accrued_rebate,
        attributes_fn=_yearly_rebate_attrs,
    ),
    EtollSensorDescription(
        key="yearly_rebate_remaining",
        translation_key="yearly_rebate_remaining",
        name="Yearly rebate remaining",
        icon="mdi:cash-minus",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.yearly_rebate_remaining,
        attributes_fn=_yearly_rebate_attrs,
    ),
    EtollSensorDescription(
        key="yearly_spend",
        translation_key="yearly_spend",
        name="Toll spend this year",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.yearly_spend,
        attributes_fn=_yearly_attrs,
    ),
    EtollSensorDescription(
        key="trips_this_week",
        translation_key="trips_this_week",
        name="Trips this week",
        icon="mdi:car-clock",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: d.weekly_trip_count,
    ),
    EtollSensorDescription(
        key="trips_this_year",
        translation_key="trips_this_year",
        name="Trips this year",
        icon="mdi:car-multiple",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.yearly_trip_count,
    ),
    EtollSensorDescription(
        key="last_trip_amount",
        translation_key="last_trip_amount",
        name="Last trip amount",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="AUD",
        value_fn=lambda d: d.last_toll.gross_amount if d.last_toll else None,
        attributes_fn=_last_toll_attrs,
    ),
    EtollSensorDescription(
        key="last_trip_at",
        translation_key="last_trip_at",
        name="Last trip at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _to_aware(d.last_toll.posted_at) if d.last_toll else None,
        attributes_fn=_last_toll_attrs,
    ),
    EtollSensorDescription(
        key="last_balance_update",
        translation_key="last_balance_update",
        name="Last balance update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _to_aware(d.account.last_balance_update),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EtollCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Account-level sensors (unchanged — backward compatible).
    async_add_entities(EtollSensor(coordinator, entry, description) for description in SENSORS)

    # Per-tag sensors: created dynamically as tag serials are discovered.
    _registered_tags: set[int] = set()

    def _add_new_tag_sensors() -> None:
        if coordinator.data is None:
            return
        new_serials = set(coordinator.data.tags.keys()) - _registered_tags
        if not new_serials:
            return
        _LOGGER.debug("Discovered new E-Toll tag serials: %s", sorted(new_serials))
        _registered_tags.update(new_serials)
        async_add_entities(
            [
                EtollTagSensor(coordinator, entry, serial, desc)
                for serial in sorted(new_serials)
                for desc in TAG_SENSORS
            ]
        )

    _add_new_tag_sensors()
    entry.async_on_unload(coordinator.async_add_listener(lambda: _add_new_tag_sensors()))


class EtollSensor(CoordinatorEntity[EtollCoordinator], SensorEntity):
    """A sensor reading off the eToll coordinator data."""

    entity_description: EtollSensorDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: EtollCoordinator,
        entry: ConfigEntry,
        description: EtollSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        account_id = coordinator.account_id or "unknown"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(account_id))},
            "name": f"E-Toll {account_id}",
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "configuration_url": "https://account.myetoll.transport.nsw.gov.au/account-details",
        }

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)


class EtollTagSensor(CoordinatorEntity[EtollCoordinator], SensorEntity):
    """A sensor scoped to a single E-Toll tag serial."""

    entity_description: EtollTagSensorDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: EtollCoordinator,
        entry: ConfigEntry,
        tag_serial: int,
        description: EtollTagSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._tag_serial = tag_serial
        self._attr_unique_id = f"{entry.entry_id}_tag_{tag_serial}_{description.key}"
        account_id = coordinator.account_id or "unknown"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{account_id}_tag_{tag_serial}")},
            "name": f"E-Toll Tag {tag_serial}",
            "manufacturer": MANUFACTURER,
            "model": MODEL_TAG,
            "via_device": (DOMAIN, str(account_id)),
        }

    def _tag_data(self) -> EtollTagData | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.tags.get(self._tag_serial)

    @property
    def native_value(self) -> Any:
        tag = self._tag_data()
        if tag is None:
            return None
        return self.entity_description.value_fn(tag)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        tag = self._tag_data()
        if tag is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(tag)


def _to_aware(dt: datetime | None) -> datetime | None:
    """Convert naive timestamps from the API to UTC-aware ones for HA."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt
    # NSW backend returns timestamps in Sydney local time. We convert via the
    # system's local zone — same approach HA's recorder uses for its own naive
    # timestamps. For timezone-strict deployments users can run HA with TZ set
    # to Australia/Sydney.
    return dt.astimezone()
