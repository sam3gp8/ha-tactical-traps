"""Coordinator: owns one lock's BLE client and serialises all access.

Battery strategy:
  * We never hold the BLE connection open. Every operation connects, does its
    work, and disconnects, so the lock can return to low-power advertising and
    sleep between commands.
  * Background polling is infrequent ("proof of life", default every 12h) and can
    be turned off entirely (0 hours) so the lock is only contacted when a
    lock/unlock command is sent.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ADDRESS,
    CONF_PIN,
    CONF_POLL_HOURS,
    DEFAULT_POLL_HOURS,
    DOMAIN,
)
from .tactical import STATE_LOCKED, STATE_UNLOCKED, TacticalBLEClient, TacticalError

_LOGGER = logging.getLogger(__name__)


class TacticalCoordinator(DataUpdateCoordinator[dict]):
    """Polls lock status rarely and performs lock/unlock, one BLE op at a time."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        hours = entry.options.get(CONF_POLL_HOURS, DEFAULT_POLL_HOURS)
        # 0 (or unset/negative) => no background polling; command-only.
        interval = timedelta(hours=hours) if hours and hours > 0 else None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.address}",
            update_interval=interval,
        )
        self.client = TacticalBLEClient(hass, self.address, entry.data[CONF_PIN])
        self._io_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict:
        """Infrequent proof-of-life poll: connect, read, disconnect."""
        async with self._io_lock:
            try:
                state = await self.client.read_state()
            except TacticalError as err:
                raise UpdateFailed(str(err)) from err
            finally:
                await self.client.disconnect()
        return {"locked": state == STATE_LOCKED}

    async def async_set_locked(self, locked: bool) -> None:
        """Lock (True) or unlock (False); idempotent. Connects, acts, disconnects,
        and updates state from the result without a second connection."""
        target = STATE_LOCKED if locked else STATE_UNLOCKED
        async with self._io_lock:
            try:
                final = await self.client.ensure(target)
            except TacticalError as err:
                raise HomeAssistantError(str(err)) from err
            finally:
                await self.client.disconnect()
        self.async_set_updated_data({"locked": final == STATE_LOCKED})

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.disconnect()
