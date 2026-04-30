"""Config flow for the NSW E-Toll integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import EtollAuthError, EtollClient, EtollError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_WEEKLY_CAP,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_WEEKLY_CAP_AUD,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL, default=defaults.get(CONF_EMAIL, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Optional(
                CONF_SCAN_INTERVAL_MINUTES,
                default=defaults.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
            ): vol.All(int, vol.Range(min=MIN_SCAN_INTERVAL_MINUTES, max=24 * 60)),
            vol.Optional(
                CONF_WEEKLY_CAP, default=defaults.get(CONF_WEEKLY_CAP, DEFAULT_WEEKLY_CAP_AUD)
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=10_000)),
        }
    )


class EtollConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the user-driven setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                account_id = await self._validate(user_input)
            except EtollAuthError:
                errors["base"] = "invalid_auth"
            except EtollError as err:
                _LOGGER.warning("eToll connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - surface anything unexpected as generic error
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(str(account_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"E-Toll {account_id}",
                    data={**user_input, CONF_ACCOUNT_ID: account_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(self, _entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._validate(user_input)
            except EtollAuthError:
                errors["base"] = "invalid_auth"
            except EtollError as err:
                _LOGGER.warning("eToll connection error: %s", err)
                errors["base"] = "cannot_connect"
            else:
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                assert entry is not None
                self.hass.config_entries.async_update_entry(entry, data={**entry.data, **user_input})
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_user_schema(),
            errors=errors,
        )

    async def _validate(self, user_input: dict[str, Any]) -> int:
        """Authenticate with eToll and return the resolved account ID."""
        client = EtollClient(
            email=user_input[CONF_EMAIL],
            password=user_input[CONF_PASSWORD],
            session=async_get_clientsession(self.hass),
        )
        await client.authenticate()
        account = await client.get_default_account()
        return account.cod_account

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EtollOptionsFlow(config_entry)


class EtollOptionsFlow(OptionsFlow):
    """Lets the user tweak scan interval and weekly cap after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = {
            CONF_SCAN_INTERVAL_MINUTES: self._entry.options.get(
                CONF_SCAN_INTERVAL_MINUTES,
                self._entry.data.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
            ),
            CONF_WEEKLY_CAP: self._entry.options.get(
                CONF_WEEKLY_CAP,
                self._entry.data.get(CONF_WEEKLY_CAP, DEFAULT_WEEKLY_CAP_AUD),
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL_MINUTES, default=defaults[CONF_SCAN_INTERVAL_MINUTES]
                    ): vol.All(int, vol.Range(min=MIN_SCAN_INTERVAL_MINUTES, max=24 * 60)),
                    vol.Optional(
                        CONF_WEEKLY_CAP, default=defaults[CONF_WEEKLY_CAP]
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=10_000)),
                }
            ),
        )
