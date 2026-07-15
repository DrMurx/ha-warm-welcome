"""Switch entities exposing room settings."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.switch import ENTITY_ID_FORMAT, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VacationHeatingConfigEntry
from .const import CONF_SET_PRESET, CONF_SET_TEMPERATURE
from .coordinator import VacationHeatingCoordinator
from .entity import VacationHeatingRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VacationHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the action switches of every room."""
    for subentry_id, coordinator in entry.runtime_data.rooms.items():
        async_add_entities(
            [
                ActionSwitch(coordinator, CONF_SET_PRESET),
                ActionSwitch(coordinator, CONF_SET_TEMPERATURE),
            ],
            config_subentry_id=subentry_id,
        )


class ActionSwitch(VacationHeatingRoomEntity, SwitchEntity):
    """Whether one aspect of the climate entity is set at the heating start."""

    _attr_entity_category = EntityCategory.CONFIG

    OBJECT_ID_SUFFIXES: ClassVar[dict[str, str]] = {
        CONF_SET_PRESET: "use_preset",
        CONF_SET_TEMPERATURE: "use_temperature",
    }

    def __init__(self, coordinator: VacationHeatingCoordinator, key: str) -> None:
        """Initialize the switch for one action flag."""
        super().__init__(coordinator, key)
        self._suggest_object_id(ENTITY_ID_FORMAT, self.OBJECT_ID_SUFFIXES[key])
        self._attr_translation_key = key
        self._key = key

    @property
    def is_on(self) -> bool:
        """Whether this action is enabled."""
        return bool(self.coordinator.settings.get(self._key))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the action in the room subentry."""
        self._update_setting(self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the action in the room subentry."""
        self._update_setting(self._key, False)
