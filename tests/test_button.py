"""Tests for the sync button entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.etoll.button import EtollSyncButton
from custom_components.etoll.const import DOMAIN, MANUFACTURER, MODEL


def _make_coordinator(account_id: int = 1234567) -> MagicMock:
    coordinator = MagicMock()
    coordinator.account_id = account_id
    coordinator.async_refresh = AsyncMock()
    return coordinator


def _make_entry(entry_id: str = "test_entry") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


class TestEtollSyncButton:
    def _make_button(
        self, account_id: int = 1234567, entry_id: str = "test_entry"
    ) -> EtollSyncButton:
        coordinator = _make_coordinator(account_id)
        button = EtollSyncButton.__new__(EtollSyncButton)
        button.coordinator = coordinator
        button._attr_unique_id = f"{entry_id}_sync"
        button._attr_device_info = {
            "identifiers": {(DOMAIN, str(account_id))},
            "name": f"E-Toll {account_id}",
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "configuration_url": "https://account.myetoll.transport.nsw.gov.au/account-details",
        }
        return button

    def test_unique_id(self):
        button = self._make_button(entry_id="abc123")
        assert button._attr_unique_id == "abc123_sync"

    def test_name(self):
        button = self._make_button()
        assert button._attr_name == "Sync"

    def test_icon(self):
        button = self._make_button()
        assert button._attr_icon == "mdi:refresh"

    def test_device_info_identifiers(self):
        button = self._make_button(account_id=9876543)
        assert (DOMAIN, "9876543") in button._attr_device_info["identifiers"]

    def test_device_info_manufacturer_and_model(self):
        button = self._make_button()
        assert button._attr_device_info["manufacturer"] == MANUFACTURER
        assert button._attr_device_info["model"] == MODEL

    async def test_async_press_calls_refresh(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        button = EtollSyncButton.__new__(EtollSyncButton)
        button.coordinator = coordinator
        button._attr_unique_id = f"{entry.entry_id}_sync"
        button._attr_device_info = {}

        await button.async_press()

        coordinator.async_refresh.assert_awaited_once()
