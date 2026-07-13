"""Coordinator that predicts and triggers the vacation re-heat."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_SET_PRESET,
    ACTION_SET_TEMPERATURE,
    CONF_ACTION,
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_PRESET_MODE,
    CONF_PRESET_TEMPERATURES,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    MAX_LOOKBACK,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)
from .heating_model import (
    ForecastPoint,
    PredictionResult,
    compute_start,
    parse_heat_rates,
    parse_preset_temperatures,
)

_LOGGER = logging.getLogger(__name__)

FORECAST_TYPES = ("hourly", "twice_daily", "daily")


class VacationHeatingCoordinator(DataUpdateCoordinator[PredictionResult | None]):
    """Recompute the heating start time and fire the configured action."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.arrival: datetime | None = None
        self.forecast_type: str | None = None
        self.forecast: list[ForecastPoint] = []
        self.triggered_for: str | None = None
        self._unsub_trigger: CALLBACK_TYPE | None = None

    async def async_restore(self) -> None:
        """Restore the trigger guard so a restart does not re-fire the action."""
        data = await self._store.async_load()
        if data:
            self.triggered_for = data.get("triggered_for")

    async def async_remove_store(self) -> None:
        """Delete persisted state when the entry is removed."""
        await self._store.async_remove()

    @callback
    def cancel_trigger(self) -> None:
        """Cancel a scheduled heating start."""
        if self._unsub_trigger is not None:
            self._unsub_trigger()
            self._unsub_trigger = None

    async def _async_update_data(self) -> PredictionResult | None:
        options = self.config_entry.options
        self.arrival = arrival = self._compute_arrival()
        if arrival is None or arrival <= dt_util.utcnow():
            # No (future) vacation end configured: idle.
            self.cancel_trigger()
            self.forecast = []
            return None

        current_temp = self._current_temperature()
        if current_temp is None:
            raise UpdateFailed(
                f"No current temperature available from {options[CONF_CLIMATE_ENTITY]}"
            )

        rates = parse_heat_rates(options[CONF_HEAT_RATES])
        forecast = await self._async_get_forecast()
        result = compute_start(
            arrival,
            current_temp,
            self._prediction_target(),
            forecast,
            rates,
            max_lookback=MAX_LOOKBACK,
        )
        # Kept for charting; clipped to the prediction window.
        self.forecast = [point for point in forecast if point.time <= arrival]
        self._schedule_trigger(result.start, arrival)
        return result

    def _prediction_target(self) -> float:
        """Temperature the room is expected to reach.

        A preset-only action heats to the preset's own setpoint, which
        cannot be read from the climate entity; use the configured preset
        temperature map and fall back to the target temperature.
        """
        options = self.config_entry.options
        if options[CONF_ACTION] == ACTION_SET_PRESET:
            presets = parse_preset_temperatures(
                options.get(CONF_PRESET_TEMPERATURES) or []
            )
            target = presets.get(options.get(CONF_PRESET_MODE, ""))
            if target is not None:
                return target
        return float(options[CONF_TARGET_TEMPERATURE])

    def _compute_arrival(self) -> datetime | None:
        """Arrival datetime from the end date entity.

        Naive values are interpreted in Home Assistant's local time zone;
        date-only values (an input_datetime without time) fall back to
        midnight.
        """
        options = self.config_entry.options
        state = self.hass.states.get(options[CONF_END_DATE_ENTITY])
        if state is None or state.state in ("unknown", "unavailable"):
            return None

        if (arrival := dt_util.parse_datetime(state.state)) is not None:
            return dt_util.as_utc(arrival)

        _LOGGER.warning(
            "Cannot parse state %r of %s as a datetime",
            state.state,
            options[CONF_END_DATE_ENTITY],
        )
        return None

    def _current_temperature(self) -> float | None:
        state = self.hass.states.get(self.config_entry.options[CONF_CLIMATE_ENTITY])
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        current = state.attributes.get("current_temperature")
        if current is None:
            return None
        return float(current)

    async def _async_get_forecast(self) -> list[ForecastPoint]:
        """Fetch the forecast, preferring hourly resolution."""
        entity_id = self.config_entry.options[CONF_WEATHER_ENTITY]
        for forecast_type in FORECAST_TYPES:
            try:
                response = await self.hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {"entity_id": entity_id, "type": forecast_type},
                    blocking=True,
                    return_response=True,
                )
            except HomeAssistantError:
                continue
            raw = (response or {}).get(entity_id, {}).get("forecast") or []
            points = self._parse_forecast(raw, forecast_type)
            if points:
                self.forecast_type = forecast_type
                return points
        raise UpdateFailed(f"No forecast available from {entity_id}")

    @staticmethod
    def _parse_forecast(
        raw: list[dict[str, Any]], forecast_type: str
    ) -> list[ForecastPoint]:
        points: list[ForecastPoint] = []
        for item in raw:
            when = dt_util.parse_datetime(str(item.get("datetime")))
            temperature = item.get("temperature")
            if when is None or temperature is None:
                continue
            temperature = float(temperature)
            if forecast_type == "daily" and item.get("templow") is not None:
                # Daily forecasts give a high/low; use the midpoint.
                temperature = (temperature + float(item["templow"])) / 2
            points.append(ForecastPoint(dt_util.as_utc(when), temperature))
        return points

    @callback
    def _schedule_trigger(self, start: datetime, arrival: datetime) -> None:
        self.cancel_trigger()
        if self.triggered_for == arrival.isoformat():
            return
        # If the start already passed (e.g. HA was down), fire right away.
        fire_at = max(start, dt_util.utcnow() + timedelta(seconds=1))
        self._unsub_trigger = async_track_point_in_time(
            self.hass, self._async_trigger, fire_at
        )

    async def _async_trigger(self, _now: datetime) -> None:
        """Turn the heating back on."""
        self._unsub_trigger = None
        arrival = self.arrival
        if (
            arrival is None
            or arrival <= dt_util.utcnow()
            or self.triggered_for == arrival.isoformat()
        ):
            return

        options = self.config_entry.options
        entity_id = options[CONF_CLIMATE_ENTITY]
        action = options[CONF_ACTION]
        _LOGGER.info(
            "Starting pre-heat of %s for arrival at %s (action: %s)",
            entity_id,
            arrival,
            action,
        )
        try:
            if action != ACTION_SET_TEMPERATURE:
                await self.hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": options[CONF_PRESET_MODE]},
                    blocking=True,
                )
            if action != ACTION_SET_PRESET:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {
                        "entity_id": entity_id,
                        "temperature": float(options[CONF_TARGET_TEMPERATURE]),
                    },
                    blocking=True,
                )
        except HomeAssistantError:
            _LOGGER.exception("Failed to start heating on %s, retrying in 5 minutes", entity_id)
            self._unsub_trigger = async_track_point_in_time(
                self.hass, self._async_trigger, dt_util.utcnow() + timedelta(minutes=5)
            )
            return

        self.triggered_for = arrival.isoformat()
        await self._store.async_save({"triggered_for": self.triggered_for})
        self.async_update_listeners()
