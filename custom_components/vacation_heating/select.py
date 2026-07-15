"""Select entities exposing room settings."""

from __future__ import annotations

from homeassistant.components.select import ENTITY_ID_FORMAT, SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VacationHeatingConfigEntry
from .const import CONF_CLIMATE_ENTITY, CONF_PRESET_MODE, CONF_SET_PRESET
from .coordinator import VacationHeatingCoordinator
from .entity import VacationHeatingRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VacationHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the preset select of every room."""
    for subentry_id, coordinator in entry.runtime_data.rooms.items():
        async_add_entities(
            [PresetModeSelect(coordinator)], config_subentry_id=subentry_id
        )


class PresetModeSelect(VacationHeatingRoomEntity, SelectEntity):
    """The preset to set at the heating start."""

    _attr_translation_key = "preset_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VacationHeatingCoordinator) -> None:
        """Initialize the preset select."""
        super().__init__(coordinator, CONF_PRESET_MODE)
        self._suggest_object_id(ENTITY_ID_FORMAT, "target_preset")

    @property
    def available(self) -> bool:
        """Grayed out while 'Set preset at heating start' is off."""
        return super().available and bool(
            self.coordinator.settings.get(CONF_SET_PRESET)
        )

    @property
    def options(self) -> list[str]:
        """The climate entity's advertised presets plus the configured one.

        Including the configured value keeps the entity valid while the
        climate entity is unavailable or no longer offers that preset.
        """
        state = self.coordinator.hass.states.get(
            self.coordinator.settings[CONF_CLIMATE_ENTITY]
        )
        presets = [
            str(preset)
            for preset in (state.attributes.get("preset_modes") if state else None) or []
        ]
        current = self.current_option
        if current and current not in presets:
            presets.append(current)
        return presets

    @property
    def current_option(self) -> str | None:
        """The configured preset."""
        return self.coordinator.settings.get(CONF_PRESET_MODE)

    async def async_select_option(self, option: str) -> None:
        """Store the new preset in the room subentry."""
        self._update_setting(CONF_PRESET_MODE, option)
