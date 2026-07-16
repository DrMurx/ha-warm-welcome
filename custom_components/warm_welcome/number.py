"""Number entities exposing room settings."""

from __future__ import annotations

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WarmWelcomeConfigEntry
from .const import (
    CONF_FLOOR_WARMUP_HOURS,
    CONF_SET_TEMPERATURE,
    CONF_TARGET_TEMPERATURE,
    DEFAULT_FLOOR_WARMUP_HOURS,
    DOMAIN,
    FLOOR_WARMUP_RANGE,
    TARGET_TEMPERATURE_RANGE_C,
    TARGET_TEMPERATURE_RANGE_F,
)
from .coordinator import WarmWelcomeCoordinator
from .entity import WarmWelcomeRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WarmWelcomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the shared warm-up number and the target number of every room."""
    async_add_entities([FloorWarmupNumber(entry)])
    for subentry_id, coordinator in entry.runtime_data.rooms.items():
        async_add_entities(
            [TargetTemperatureNumber(coordinator)], config_subentry_id=subentry_id
        )


class FloorWarmupNumber(NumberEntity):
    """Hours the floor's thermal mass needs before heating the room.

    Shared by all rooms of the entry, so it lives on the entry-level
    device and writes into the entry options (like the shared entities
    edited in the options flow).
    """

    _attr_has_entity_name = True
    # The value only changes through options updates, which reload the
    # entry and rebuild this entity — nothing to poll.
    _attr_should_poll = False
    _attr_translation_key = CONF_FLOOR_WARMUP_HOURS
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX
    _attr_native_min_value, _attr_native_max_value = FLOOR_WARMUP_RANGE
    _attr_native_step = 0.25

    def __init__(self, entry: WarmWelcomeConfigEntry) -> None:
        """Initialize the number on the entry-level device."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{CONF_FLOOR_WARMUP_HOURS}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="DrMurx",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float:
        """The configured floor warm-up time in hours."""
        return float(
            self._entry.options.get(
                CONF_FLOOR_WARMUP_HOURS, DEFAULT_FLOOR_WARMUP_HOURS
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        """Store the new warm-up time in the entry options.

        The entry's update listener reloads the entry, which recomputes
        every room with the new value.
        """
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_FLOOR_WARMUP_HOURS: value},
        )


class TargetTemperatureNumber(WarmWelcomeRoomEntity, NumberEntity):
    """The room temperature to reach by the arrival, editable in place."""

    _attr_translation_key = "target_temperature"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.5

    def __init__(self, coordinator: WarmWelcomeCoordinator) -> None:
        """Initialize with the bounds of the unit system."""
        super().__init__(coordinator, CONF_TARGET_TEMPERATURE)
        self._suggest_object_id(ENTITY_ID_FORMAT, "target_temperature")
        unit = coordinator.hass.config.units.temperature_unit
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value, self._attr_native_max_value = (
            TARGET_TEMPERATURE_RANGE_F
            if unit == UnitOfTemperature.FAHRENHEIT
            else TARGET_TEMPERATURE_RANGE_C
        )

    @property
    def available(self) -> bool:
        """Grayed out while 'Set temperature at heating start' is off."""
        return super().available and bool(
            self.coordinator.settings.get(CONF_SET_TEMPERATURE)
        )

    @property
    def native_value(self) -> float:
        """The configured target temperature."""
        return float(self.coordinator.settings[CONF_TARGET_TEMPERATURE])

    async def async_set_native_value(self, value: float) -> None:
        """Store the new target temperature in the room subentry."""
        self._update_setting(CONF_TARGET_TEMPERATURE, value)
