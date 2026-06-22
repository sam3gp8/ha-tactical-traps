"""Coordinator: owns one lock's BLE client and serialises all access.

Battery vs. latency:
  * By default we never hold the BLE connection open. Every operation connects,
    acts, and disconnects, so the lock can sleep between commands (best battery).
  * `keep_alive_seconds` keeps the connection (and login session) open for a short
    window after an operation. Within that window the next command — typically the
    auto-relock or a quick re-open — skips the slow reconnect + login and is
    near-instant. 0 keeps today's max-battery behaviour.
  * Background "proof of life" polling is infrequent (default 12h) or off (0).
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
    CONF_KEEP_ALIVE,
    CONF_PIN,
    CONF_POLL_HOURS,
    DEFAULT_KEEP_ALIVE,
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
        self._keep_alive = int(entry.options.get(CONF_KEEP_ALIVE, DEFAULT_KEEP_ALIVE))
        self._io_lock = asyncio.Lock()
        self._disconnect_task: asyncio.Task | None = None

    # ---- run one BLE operation, then disconnect now or after the keep-alive ----
    async def _run(self, action):
        async with self._io_lock:
            self._cancel_pending_disconnect()
            try:
                return await action()
            finally:
                if self._keep_alive > 0:
                    self._disconnect_task = self.hass.async_create_background_task(
                        self._deferred_disconnect(), name=f"{DOMAIN}-disconnect"
                    )
                else:
                    await self.client.disconnect()

    def _cancel_pending_disconnect(self) -> None:
        if self._disconnect_task and not self._disconnect_task.done():
            self._disconnect_task.cancel()
        self._disconnect_task = None

    async def _deferred_disconnect(self) -> None:
        try:
            await asyncio.sleep(self._keep_alive)
            async with self._io_lock:
                await self.client.disconnect()
        except asyncio.CancelledError:
            pass

    # ---- coordinator API ----
    async def _async_update_data(self) -> dict:
        """Infrequent proof-of-life poll."""
        try:
            state = await self._run(lambda: self.client.read_state())
        except TacticalError as err:
            raise UpdateFailed(str(err)) from err
        return {"locked": state == STATE_LOCKED}

    async def async_set_locked(self, locked: bool) -> None:
        """Lock (True) or unlock (False); idempotent. Updates state from the
        command result without a second connection."""
        target = STATE_LOCKED if locked else STATE_UNLOCKED
        try:
            final = await self._run(lambda: self.client.ensure(target))
        except TacticalError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data({"locked": final == STATE_LOCKED})

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        self._cancel_pending_disconnect()
        await self.client.disconnect()
