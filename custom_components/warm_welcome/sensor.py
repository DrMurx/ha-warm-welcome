"""Sensors exposing the predicted heating start."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WarmWelcomeConfigEntry
from .const import (
    ATTR_ARRIVAL,
    ATTR_BEYOND_FORECAST,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_DEFICIT,
    ATTR_FORECAST,
    ATTR_FORECAST_TYPE,
    ATTR_PREDICTED_TEMPERATURES,
    ATTR_PREHEAT_ACTIVE,
    ATTR_PREHEAT_HOURS,
    ATTR_TARGET_AT_RISK,
    ATTR_TARGET_REACHED,
    ATTR_TARGET_TEMPERATURE,
    ATTR_TRIGGERED_FOR,
    DOMAIN,
)
from .coordinator import ForecastCoordinator, WarmWelcomeCoordinator
from .entity import WarmWelcomeRoomEntity


def _predicted_temperatures(
    curve: list[tuple[datetime, float]],
) -> list[dict[str, Any]]:
    """Serialize the indoor trajectory from the heating start to arrival."""
    return [
        {"datetime": when.isoformat(), "temperature": round(temperature, 2)}
        for when, temperature in curve
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WarmWelcomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the shared forecast sensor and the sensors of every room."""
    async_add_entities([OutdoorForecastSensor(entry.runtime_data.forecast, entry)])
    for subentry_id, coordinator in entry.runtime_data.rooms.items():
        async_add_entities(
            [HeatingStartSensor(coordinator), RequiredPreheatSensor(coordinator)],
            config_subentry_id=subentry_id,
        )


class WarmWelcomeSensor(WarmWelcomeRoomEntity, SensorEntity):
    """Base class for Warm Welcome sensors."""

    def __init__(
        self,
        coordinator: WarmWelcomeCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(coordinator, description.key)


class OutdoorForecastSensor(
    CoordinatorEntity[ForecastCoordinator], SensorEntity
):
    """The shared outdoor forecast, exposed for charting."""

    _attr_has_entity_name = True
    # The forecast series would bloat the recorder database; cards read
    # the live state, so history is not needed.
    _unrecorded_attributes = frozenset({ATTR_FORECAST})

    def __init__(
        self,
        coordinator: ForecastCoordinator,
        entry: WarmWelcomeConfigEntry,
    ) -> None:
        """Initialize the sensor on the entry-level device."""
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(
            key="outdoor_forecast",
            translation_key="outdoor_forecast",
            device_class=SensorDeviceClass.TEMPERATURE,
            suggested_display_precision=1,
        )
        self._attr_native_unit_of_measurement = (
            coordinator.hass.config.units.temperature_unit
        )
        self._attr_unique_id = f"{entry.entry_id}_outdoor_forecast"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        """The forecast temperature of the current interval."""
        if not (data := self.coordinator.data):
            return None
        return data[0].temperature

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the forecast points."""
        return {
            ATTR_FORECAST_TYPE: self.coordinator.forecast_type,
            ATTR_FORECAST: [
                {
                    "datetime": point.time.isoformat(),
                    "temperature": round(point.temperature, 2),
                }
                for point in self.coordinator.data or []
            ],
        }


class HeatingStartSensor(WarmWelcomeSensor):
    """When the heating must be turned on."""

    # The chart series would bloat the recorder database; cards read the
    # live state, so history is not needed.
    _unrecorded_attributes = frozenset({ATTR_PREDICTED_TEMPERATURES})

    def __init__(self, coordinator: WarmWelcomeCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="heating_start",
                translation_key="heating_start",
                device_class=SensorDeviceClass.TIMESTAMP,
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the computed heating start time."""
        if (data := self.coordinator.data) is None:
            return None
        return data.start

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose prediction details."""
        coordinator = self.coordinator
        attrs: dict[str, Any] = {
            ATTR_TRIGGERED_FOR: coordinator.triggered_for,
            ATTR_PREHEAT_ACTIVE: coordinator.preheat_active,
        }
        if (data := coordinator.data) is not None:
            unit = self.hass.config.units.temperature_unit
            attrs.update(
                {
                    ATTR_PREHEAT_HOURS: round(data.preheat_hours, 2),
                    ATTR_DEFICIT: f"{round(data.deficit, 2)} {unit}",
                    ATTR_CURRENT_TEMPERATURE: coordinator.current_temperature,
                    ATTR_TARGET_TEMPERATURE: coordinator.target_temperature,
                    ATTR_BEYOND_FORECAST: data.beyond_forecast,
                    ATTR_TARGET_AT_RISK: coordinator.target_at_risk,
                    ATTR_TARGET_REACHED: coordinator.target_reached,
                    ATTR_FORECAST_TYPE: coordinator.forecast_type,
                    ATTR_ARRIVAL: coordinator.arrival,
                    ATTR_PREDICTED_TEMPERATURES: _predicted_temperatures(data.curve),
                }
            )
        return attrs


class RequiredPreheatSensor(WarmWelcomeSensor):
    """How long the room needs to reach the target temperature."""

    def __init__(self, coordinator: WarmWelcomeCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="required_preheat",
                translation_key="required_preheat",
                device_class=SensorDeviceClass.DURATION,
                native_unit_of_measurement=UnitOfTime.HOURS,
                suggested_display_precision=1,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def native_value(self) -> float | None:
        """Return the required pre-heat duration in hours."""
        if (data := self.coordinator.data) is None:
            return None
        return data.preheat_hours
