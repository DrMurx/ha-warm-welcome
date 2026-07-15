"""Base entity for the entities of a room subentry."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import WarmWelcomeCoordinator


class WarmWelcomeRoomEntity(CoordinatorEntity[WarmWelcomeCoordinator]):
    """An entity on the device of one room."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WarmWelcomeCoordinator, key: str) -> None:
        """Initialize the entity on the room's device."""
        super().__init__(coordinator)
        subentry = coordinator.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    def _suggest_object_id(self, entity_id_format: str, suffix: str) -> None:
        """Suggest ``<room>_warm_welcome_<suffix>`` as the entity id.

        Only a suggestion for the initial registration: entities already
        in the registry keep their id (the unique id is unchanged).
        """
        self.entity_id = entity_id_format.format(
            f"{slugify(self.coordinator.subentry.title)}_warm_welcome_{suffix}"
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
