"""Config flow for Tactical Traps (Bluetooth discovery or manual entry)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_AUTO_RELOCK,
    CONF_KEEP_ALIVE,
    CONF_PIN,
    CONF_POLL_HOURS,
    DEFAULT_AUTO_RELOCK,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_POLL_HOURS,
    DOMAIN,
)
from .tactical import TacticalBLEClient, TacticalError


async def _validate(hass, address: str, pin: str) -> str | None:
    """Try to connect + log in. Returns an error key, or None on success."""
    client = TacticalBLEClient(hass, address, pin)
    try:
        await client.validate()
    except TacticalError:
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        return "unknown"
    return None


class TacticalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tactical Traps."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """A FFF0 device was discovered by Home Assistant."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovered_address = discovery_info.address
        self._discovered_name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered lock and ask for its PIN."""
        errors: dict[str, str] = {}
        if user_input is not None:
            err = await _validate(self.hass, self._discovered_address, user_input[CONF_PIN])
            if err:
                errors["base"] = err
            else:
                return self.async_create_entry(
                    title=self._discovered_name,
                    data={CONF_ADDRESS: self._discovered_address, CONF_PIN: user_input[CONF_PIN]},
                )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required(CONF_PIN): cv.string}),
            description_placeholders={"name": self._discovered_name or ""},
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup, or pick from devices Home Assistant has already seen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            err = await _validate(self.hass, address, user_input[CONF_PIN])
            if err:
                errors["base"] = err
            else:
                return self.async_create_entry(
                    title=user_input.get("name") or f"Tactical Traps {address}",
                    data={CONF_ADDRESS: address, CONF_PIN: user_input[CONF_PIN]},
                )

        # Offer discovered, not-yet-configured FFF0 devices as suggestions
        current = self._async_current_ids()
        seen = {
            si.address: (si.name or si.address)
            for si in async_discovered_service_info(self.hass)
            if si.address not in current
        }
        addr_field = vol.In(seen) if seen else cv.string

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): addr_field,
                    vol.Required(CONF_PIN): cv.string,
                    vol.Optional("name"): cv.string,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TacticalOptionsFlow(config_entry)


class TacticalOptionsFlow(OptionsFlow):
    """Poll interval and auto-relock options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opts = self._entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_HOURS,
                        default=opts.get(CONF_POLL_HOURS, DEFAULT_POLL_HOURS),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=168)),
                    vol.Optional(
                        CONF_AUTO_RELOCK,
                        default=opts.get(CONF_AUTO_RELOCK, DEFAULT_AUTO_RELOCK),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
                    vol.Optional(
                        CONF_KEEP_ALIVE,
                        default=opts.get(CONF_KEEP_ALIVE, DEFAULT_KEEP_ALIVE),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=300)),
                }
            ),
        )
