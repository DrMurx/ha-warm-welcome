"""Websocket API feeding the bundled Lovelace card."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import voluptuous as vol

from .const import DOMAIN, SIGNAL_UPDATE


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_subscribe)


def _serialize(points: list[tuple[datetime, float]]) -> list[dict[str, Any]]:
    return [
        {"datetime": when.isoformat(), "temperature": round(temperature, 2)}
        for when, temperature in points
    ]


@callback
def _payload(hass: HomeAssistant) -> dict[str, Any]:
    """Chart data of the (single) config entry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        # The refresh dispatched at the end of async_setup_entry (after a
        # reload) fires while the entry is still SETUP_IN_PROGRESS; its
        # runtime data is already in place by then.
        if entry.state not in (
            ConfigEntryState.LOADED,
            ConfigEntryState.SETUP_IN_PROGRESS,
        ):
            continue
        data = getattr(entry, "runtime_data", None)
        if data is None:
            continue
        arrival: datetime | None = None
        rooms: list[dict[str, Any]] = []
        for coordinator in data.rooms.values():
            arrival = coordinator.arrival or arrival
            prediction = coordinator.data
            rooms.append(
                {
                    "name": coordinator.subentry.title,
                    "start": prediction.start.isoformat() if prediction else None,
                    "beyond_forecast": (
                        prediction.beyond_forecast if prediction else False
                    ),
                    "curve": _serialize(prediction.curve) if prediction else [],
                }
            )
        return {
            "arrival": arrival.isoformat() if arrival else None,
            "unit": hass.config.units.temperature_unit,
            "forecast": _serialize(
                [(point.time, point.temperature) for point in data.forecast.data or []]
            ),
            "rooms": rooms,
        }
    return {
        "arrival": None,
        "unit": hass.config.units.temperature_unit,
        "forecast": [],
        "rooms": [],
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Push the chart data to the card, immediately and on every update."""

    @callback
    def _push() -> None:
        connection.send_event(msg["id"], _payload(hass))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_UPDATE, _push
    )
    connection.send_result(msg["id"])
    _push()
