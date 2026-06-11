"""Coordinator: owns one lock's BLE client and serialises all access."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ADDRESS,
    CONF_PIN,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .tactical import STATE_LOCKED, STATE_UNLOCKED, TacticalBLEClient, TacticalError

_LOGGER = logging.getLogger(__name__)


class TacticalCoordinator(DataUpdateCoordinator[dict]):
    """Polls lock status and performs lock/unlock, one BLE op at a time."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        poll = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.address}",
            update_interval=timedelta(seconds=poll),
        )
        self.client = TacticalBLEClient(hass, self.address, entry.data[CONF_PIN])
        self._io_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict:
        async with self._io_lock:
            try:
                state = await self.client.read_state()
            except TacticalError as err:
                raise UpdateFailed(str(err)) from err
        return {"locked": state == STATE_LOCKED, "available": True}

    async def async_set_locked(self, locked: bool) -> None:
        """Lock (True) or unlock (False); idempotent. Refreshes state after."""
        target = STATE_LOCKED if locked else STATE_UNLOCKED
        async with self._io_lock:
            try:
                await self.client.ensure(target)
            except TacticalError as err:
                raise UpdateFailed(str(err)) from err
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.disconnect()
