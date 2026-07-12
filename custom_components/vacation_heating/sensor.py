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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import VacationHeatingConfigEntry
from .const import (
    ATTR_ARRIVAL,
    ATTR_BEYOND_FORECAST,
    ATTR_DEFICIT,
    ATTR_FORECAST_TYPE,
    ATTR_PREHEAT_HOURS,
    ATTR_TRIGGERED_FOR,
    DOMAIN,
)
from .coordinator import VacationHeatingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VacationHeatingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [HeatingStartSensor(coordinator, entry), RequiredPreheatSensor(coordinator, entry)]
    )


class VacationHeatingSensor(
    CoordinatorEntity[VacationHeatingCoordinator], SensorEntity
):
    """Base class for vacation heating sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VacationHeatingCoordinator,
        entry: VacationHeatingConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )


class HeatingStartSensor(VacationHeatingSensor):
    """When the heating must be turned on."""

    def __init__(
        self,
        coordinator: VacationHeatingCoordinator,
        entry: VacationHeatingConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
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
        attrs: dict[str, Any] = {ATTR_TRIGGERED_FOR: coordinator.triggered_for}
        if (data := coordinator.data) is not None:
            attrs.update(
                {
                    ATTR_PREHEAT_HOURS: round(data.preheat_hours, 2),
                    ATTR_DEFICIT: round(data.deficit, 2),
                    ATTR_BEYOND_FORECAST: data.beyond_forecast,
                    ATTR_FORECAST_TYPE: coordinator.forecast_type,
                    ATTR_ARRIVAL: coordinator.arrival,
                }
            )
        return attrs


class RequiredPreheatSensor(VacationHeatingSensor):
    """How long the room needs to reach the target temperature."""

    def __init__(
        self,
        coordinator: VacationHeatingCoordinator,
        entry: VacationHeatingConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
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
