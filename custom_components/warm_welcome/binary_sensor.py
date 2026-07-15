"""Binary sensor alerting when a room will not be warm in time."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WarmWelcomeConfigEntry
from .const import ATTR_ARRIVAL, ATTR_TARGET_REACHED
from .coordinator import WarmWelcomeCoordinator
from .entity import WarmWelcomeRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WarmWelcomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the target-at-risk alert of every room."""
    for subentry_id, coordinator in entry.runtime_data.rooms.items():
        async_add_entities(
            [TargetAtRiskSensor(coordinator)], config_subentry_id=subentry_id
        )


class TargetAtRiskSensor(WarmWelcomeRoomEntity, BinarySensorEntity):
    """On when the target temperature will not be reached by the arrival."""

    def __init__(self, coordinator: WarmWelcomeCoordinator) -> None:
        """Initialize the sensor."""
        self.entity_description = BinarySensorEntityDescription(
            key="target_at_risk",
            translation_key="target_at_risk",
            device_class=BinarySensorDeviceClass.PROBLEM,
        )
        super().__init__(coordinator, self.entity_description.key)

    @property
    def is_on(self) -> bool:
        """True when the room is predicted to miss the target at arrival."""
        return self.coordinator.data is not None and self.coordinator.target_at_risk

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the predicted reach time and the arrival it is checked against."""
        if self.coordinator.data is None:
            return {}
        return {
            ATTR_TARGET_REACHED: self.coordinator.target_reached,
            ATTR_ARRIVAL: self.coordinator.arrival,
        }
