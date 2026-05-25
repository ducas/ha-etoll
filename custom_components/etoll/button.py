"""Button entity: manually trigger a coordinator refresh."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import EtollCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EtollCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EtollSyncButton(coordinator, entry)])


class EtollSyncButton(CoordinatorEntity[EtollCoordinator], ButtonEntity):
    """Button that triggers an immediate coordinator refresh."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_name = "Sync"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: EtollCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_sync"
        account_id = coordinator.account_id or "unknown"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(account_id))},
            "name": f"E-Toll {account_id}",
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "configuration_url": "https://account.myetoll.transport.nsw.gov.au/account-details",
        }

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
