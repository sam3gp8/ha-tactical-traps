"""Lock platform for Tactical Traps."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_AUTO_RELOCK, DEFAULT_AUTO_RELOCK, DOMAIN
from .coordinator import TacticalCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TacticalCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TacticalLock(coordinator, entry)])


class TacticalLock(CoordinatorEntity[TacticalCoordinator], LockEntity):
    """A Tactical Traps cabinet lock."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: TacticalCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._cancel_relock = None
        title = entry.title or f"Tactical Traps {coordinator.address}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=title,
            manufacturer="Tactical Traps",
            model="BLE concealment cabinet (FFF0)",
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.last_update_success

    @property
    def is_locked(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("locked")

    async def async_lock(self, **kwargs: Any) -> None:
        self._cancel_pending_relock()
        await self.coordinator.async_set_locked(True)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_locked(False)
        self._schedule_relock()

    # ---- auto-relock (safety for gravity-drop cabinets) ----
    def _relock_delay(self) -> int:
        return int(self._entry.options.get(CONF_AUTO_RELOCK, DEFAULT_AUTO_RELOCK))

    def _schedule_relock(self) -> None:
        delay = self._relock_delay()
        if delay <= 0:
            return
        self._cancel_pending_relock()

        async def _do_relock(_now) -> None:
            self._cancel_relock = None
            _LOGGER.debug("Auto-relocking %s after %ss", self.coordinator.address, delay)
            try:
                await self.coordinator.async_set_locked(True)
            except Exception as err:  # noqa: BLE001 - log and surface, don't crash
                _LOGGER.warning("Auto-relock of %s failed: %s", self.coordinator.address, err)

        self._cancel_relock = async_call_later(self.hass, delay, _do_relock)

    @callback
    def _cancel_pending_relock(self) -> None:
        if self._cancel_relock is not None:
            self._cancel_relock()
            self._cancel_relock = None

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_pending_relock()
        await super().async_will_remove_from_hass()
