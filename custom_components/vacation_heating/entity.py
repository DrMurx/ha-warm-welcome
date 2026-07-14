"""Base entity for the entities of a room subentry."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VacationHeatingCoordinator


class VacationHeatingRoomEntity(CoordinatorEntity[VacationHeatingCoordinator]):
    """An entity on the device of one room."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VacationHeatingCoordinator, key: str) -> None:
        """Initialize the entity on the room's device."""
        super().__init__(coordinator)
        subentry = coordinator.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    def _update_setting(self, key: str, value: Any) -> None:
        """Persist a changed room setting into the subentry.

        The entry's update listener reloads the entry, which rebuilds the
        coordinators and entities with the new value.
        """
        coordinator = self.coordinator
        self.hass.config_entries.async_update_subentry(
            coordinator.config_entry,
            coordinator.subentry,
            data={**coordinator.subentry.data, key: value},
        )
