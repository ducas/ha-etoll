"""NSW E-Toll integration for Home Assistant.

The HA-only imports are deferred into the setup/unload coroutines so that
``etoll.client`` (a pure-aiohttp module with no HA deps) can be imported and
used outside Home Assistant — for example by ``examples/test_client.py``
which runs from a plain Python.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an eToll account from a config entry."""
    from homeassistant.const import Platform

    from .const import DOMAIN
    from .coordinator import EtollCoordinator

    coordinator = EtollCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    platforms = [Platform.SENSOR, Platform.BINARY_SENSOR]
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    from homeassistant.const import Platform

    from .const import DOMAIN
    from .coordinator import EtollCoordinator

    platforms = [Platform.SENSOR, Platform.BINARY_SENSOR]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    coordinator: EtollCoordinator | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if coordinator:
        await coordinator.async_close()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (e.g. scan interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
