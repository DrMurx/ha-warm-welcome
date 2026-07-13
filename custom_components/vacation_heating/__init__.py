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
    SUBENTRY_TYPE_ROOM,
)
from .coordinator import VacationHeatingCoordinator, make_store

PLATFORMS = [Platform.SENSOR]

type VacationHeatingConfigEntry = ConfigEntry[dict[str, VacationHeatingCoordinator]]


async def async_setup_entry(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> bool:
    """Set up Vacation Heating from a config entry.

    The entry holds the shared weather and vacation end entities; each room
    is a subentry with its own coordinator.
    """
    store = make_store(hass, entry)
    stored = await store.async_load() or {}
    # Shared trigger guard map; drop guards of removed rooms.
    triggered: dict[str, str] = {
        subentry_id: value
        for subentry_id, value in (stored.get("triggered_for") or {}).items()
        if isinstance(value, str) and subentry_id in entry.subentries
    }

    coordinators: dict[str, VacationHeatingCoordinator] = {}
    # Which coordinators to refresh per tracked entity; the shared entities
    # affect every room.
    refresh_map: dict[str, list[VacationHeatingCoordinator]] = {}
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_ROOM:
            continue
        coordinator = VacationHeatingCoordinator(hass, entry, subentry, store, triggered)
        await coordinator.async_config_entry_first_refresh()
        coordinators[subentry_id] = coordinator
        refresh_map.setdefault(subentry.data[CONF_CLIMATE_ENTITY], []).append(coordinator)
        entry.async_on_unload(coordinator.cancel_trigger)
    entry.runtime_data = coordinators

    @callback
    def _tracked_entity_changed(event: Event) -> None:
        affected = refresh_map.get(event.data["entity_id"]) or coordinators.values()
        for coordinator in affected:
            entry.async_create_task(hass, coordinator.async_request_refresh())

    tracked = [
        entry.options[CONF_WEATHER_ENTITY],
        entry.options[CONF_END_DATE_ENTITY],
        *refresh_map,
    ]
    entry.async_on_unload(
        async_track_state_change_event(hass, tracked, _tracked_entity_changed)
    )
    # Subentry and options changes only notify listeners; reload to apply.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> None:
    """Reload the entry when its options or subentries change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> None:
    """Clean up persisted state when the entry is removed."""
    await make_store(hass, entry).async_remove()
