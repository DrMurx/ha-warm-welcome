"""The Vacation Heating integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import websocket
from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    SIGNAL_UPDATE,
    SUBENTRY_TYPE_ROOM,
)
from .coordinator import ForecastCoordinator, VacationHeatingCoordinator, make_store

PLATFORMS = [Platform.NUMBER, Platform.SELECT, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_FILENAME = "vacation-heating-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket API and the bundled Lovelace card."""
    websocket.async_register(hass)

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}", str(Path(__file__).parent / "frontend"), True
            )
        ]
    )
    # The version in the URL busts browser caches on upgrades.
    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"/{DOMAIN}/{CARD_FILENAME}?v={integration.version}")
    return True


@dataclass
class VacationHeatingData:
    """Runtime data of a config entry."""

    forecast: ForecastCoordinator
    rooms: dict[str, VacationHeatingCoordinator]


type VacationHeatingConfigEntry = ConfigEntry[VacationHeatingData]


async def async_setup_entry(
    hass: HomeAssistant, entry: VacationHeatingConfigEntry
) -> bool:
    """Set up Vacation Heating from a config entry.

    The entry holds the shared weather and vacation end entities and one
    forecast coordinator; each room is a subentry with its own coordinator
    consuming that forecast.
    """
    store = make_store(hass, entry)
    stored = await store.async_load() or {}
    # Shared trigger guard map; drop guards of removed rooms.
    triggered: dict[str, str] = {
        subentry_id: value
        for subentry_id, value in (stored.get("triggered_for") or {}).items()
        if isinstance(value, str) and subentry_id in entry.subentries
    }

    forecast_coordinator = ForecastCoordinator(hass, entry)
    await forecast_coordinator.async_config_entry_first_refresh()

    rooms: dict[str, VacationHeatingCoordinator] = {}
    # Which room to refresh per climate entity; the shared entities
    # affect every room.
    refresh_map: dict[str, list[VacationHeatingCoordinator]] = {}
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_ROOM:
            continue
        coordinator = VacationHeatingCoordinator(
            hass, entry, subentry, forecast_coordinator, store, triggered
        )
        await coordinator.async_config_entry_first_refresh()
        rooms[subentry_id] = coordinator
        refresh_map.setdefault(subentry.data[CONF_CLIMATE_ENTITY], []).append(coordinator)
        entry.async_on_unload(coordinator.cancel_trigger)
    entry.runtime_data = VacationHeatingData(forecast_coordinator, rooms)

    @callback
    def _forecast_updated() -> None:
        """Recompute every room on fresh forecast data."""
        for coordinator in rooms.values():
            entry.async_create_task(hass, coordinator.async_request_refresh())

    # This listener also keeps the forecast coordinator polling even
    # while the entry has no rooms yet.
    entry.async_on_unload(forecast_coordinator.async_add_listener(_forecast_updated))

    @callback
    def _notify_card() -> None:
        """Push fresh data to the card's websocket subscriptions."""
        async_dispatcher_send(hass, SIGNAL_UPDATE)

    entry.async_on_unload(forecast_coordinator.async_add_listener(_notify_card))
    for coordinator in rooms.values():
        entry.async_on_unload(coordinator.async_add_listener(_notify_card))

    @callback
    def _tracked_entity_changed(event: Event) -> None:
        entity_id = event.data["entity_id"]
        if entity_id == entry.options[CONF_WEATHER_ENTITY]:
            # Rooms follow via the forecast listener.
            entry.async_create_task(hass, forecast_coordinator.async_request_refresh())
            return
        affected = refresh_map.get(entity_id) or rooms.values()
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
    # Card subscriptions outlive entry reloads (they hang on the
    # dispatcher signal, not on the coordinators); push the new data.
    async_dispatcher_send(hass, SIGNAL_UPDATE)
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
