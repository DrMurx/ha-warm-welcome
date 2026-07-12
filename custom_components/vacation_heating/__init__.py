"""The Vacation Heating integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_WEATHER_ENTITY,
)
from .coordinator import VacationHeatingCoordinator

PLATFORMS = [Platform.SENSOR]

type VacationHeatingConfigEntry = ConfigEntry[VacationHeatingCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> bool:
    """Set up Vacation Heating from a config entry."""
    coordinator = VacationHeatingCoordinator(hass, entry)
    await coordinator.async_restore()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    @callback
    def _tracked_entity_changed(_event: Event) -> None:
        entry.async_create_task(hass, coordinator.async_request_refresh())

    tracked = [
        entry.options[CONF_CLIMATE_ENTITY],
        entry.options[CONF_WEATHER_ENTITY],
        entry.options[CONF_END_DATE_ENTITY],
    ]
    entry.async_on_unload(
        async_track_state_change_event(hass, tracked, _tracked_entity_changed)
    )
    entry.async_on_unload(coordinator.cancel_trigger)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> None:
    """Clean up persisted state when the entry is removed."""
    coordinator = VacationHeatingCoordinator(hass, entry)
    await coordinator.async_remove_store()
