"""Number entities exposing room settings."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VacationHeatingConfigEntry
from .const import (
    CONF_TARGET_TEMPERATURE,
    TARGET_TEMPERATURE_RANGE_C,
    TARGET_TEMPERATURE_RANGE_F,
)
from .coordinator import VacationHeatingCoordinator
from .entity import VacationHeatingRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VacationHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the target temperature number of every room."""
    for subentry_id, coordinator in entry.runtime_data.rooms.items():
        async_add_entities(
            [TargetTemperatureNumber(coordinator)], config_subentry_id=subentry_id
        )


class TargetTemperatureNumber(VacationHeatingRoomEntity, NumberEntity):
    """The room temperature to reach by the arrival, editable in place."""

    _attr_translation_key = "target_temperature"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.5

    def __init__(self, coordinator: VacationHeatingCoordinator) -> None:
        """Initialize with the bounds of the unit system."""
        super().__init__(coordinator, CONF_TARGET_TEMPERATURE)
        unit = coordinator.hass.config.units.temperature_unit
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value, self._attr_native_max_value = (
            TARGET_TEMPERATURE_RANGE_F
            if unit == UnitOfTemperature.FAHRENHEIT
            else TARGET_TEMPERATURE_RANGE_C
        )

    @property
    def native_value(self) -> float:
        """The configured target temperature."""
        return float(self.coordinator.settings[CONF_TARGET_TEMPERATURE])

    async def async_set_native_value(self, value: float) -> None:
        """Store the new target temperature in the room subentry."""
        self._update_setting(CONF_TARGET_TEMPERATURE, value)
