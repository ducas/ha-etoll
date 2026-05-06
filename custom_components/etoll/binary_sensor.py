"""Binary sensor: rebate eligibility for the current week."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL, MODEL_TAG
from .coordinator import EtollCoordinator, EtollTagData

_LOGGER = logging.getLogger(__name__)

REBATE_DESCRIPTION = BinarySensorEntityDescription(
    key="rebate_eligible",
    translation_key="rebate_eligible",
    name="Rebate eligible (this week)",
    icon="mdi:cash-refund",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EtollCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Account-level entity (unchanged — backward compatible).
    async_add_entities([RebateEligibleBinarySensor(coordinator, entry)])

    # Per-tag entities: created dynamically as tag serials are discovered.
    _registered_tags: set[int] = set()

    def _add_new_tag_binary_sensors() -> None:
        if coordinator.data is None:
            return
        new_serials = set(coordinator.data.tags.keys()) - _registered_tags
        if not new_serials:
            return
        _LOGGER.debug("Discovered new E-Toll tag serials (binary sensor): %s", sorted(new_serials))
        _registered_tags.update(new_serials)
        async_add_entities(
            [
                EtollTagRebateEligibleBinarySensor(coordinator, entry, serial)
                for serial in sorted(new_serials)
            ]
        )

    _add_new_tag_binary_sensors()
    entry.async_on_unload(coordinator.async_add_listener(lambda: _add_new_tag_binary_sensors()))


class RebateEligibleBinarySensor(CoordinatorEntity[EtollCoordinator], BinarySensorEntity):
    """True when toll spend this week exceeds the configured weekly cap."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    entity_description = REBATE_DESCRIPTION

    def __init__(self, coordinator: EtollCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_rebate_eligible"
        account_id = coordinator.account_id or "unknown"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(account_id))},
            "name": f"E-Toll {account_id}",
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "configuration_url": "https://account.myetoll.transport.nsw.gov.au/account-details",
        }

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.rebate_eligible

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None:
            return None
        return {
            "weekly_spend_aud": data.weekly_spend,
            "weekly_cap_aud": data.weekly_cap,
            "weekly_excess_aud": data.weekly_excess,
            "trip_count_this_week": data.weekly_trip_count,
        }


class EtollTagRebateEligibleBinarySensor(CoordinatorEntity[EtollCoordinator], BinarySensorEntity):
    """Rebate-eligible binary sensor scoped to a single tag serial."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    entity_description = REBATE_DESCRIPTION

    def __init__(
        self,
        coordinator: EtollCoordinator,
        entry: ConfigEntry,
        tag_serial: int,
    ) -> None:
        super().__init__(coordinator)
        self._tag_serial = tag_serial
        self._attr_unique_id = f"{entry.entry_id}_tag_{tag_serial}_rebate_eligible"
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
    def is_on(self) -> bool | None:
        tag = self._tag_data()
        return None if tag is None else tag.rebate_eligible

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        tag = self._tag_data()
        if tag is None:
            return None
        return {
            "weekly_spend_aud": tag.weekly_spend,
            "weekly_cap_aud": tag.weekly_cap,
            "weekly_excess_aud": tag.weekly_excess,
            "trip_count_this_week": tag.weekly_trip_count,
        }
