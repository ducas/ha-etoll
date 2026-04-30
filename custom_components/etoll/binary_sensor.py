"""Binary sensor: rebate eligibility for the current week."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import EtollCoordinator

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
    async_add_entities([RebateEligibleBinarySensor(coordinator, entry)])


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
