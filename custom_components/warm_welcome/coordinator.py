"""Coordinator that predicts and triggers the vacation re-heat."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_PRESET_TEMPERATURES,
    CONF_SET_PRESET,
    CONF_SET_TEMPERATURE,
    CONF_TARGET_PRESET,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    LATE_TOLERANCE,
    MAX_LOOKBACK,
    STORAGE_VERSION,
    TRIGGER_SETTLE_DELAY,
    UPDATE_INTERVAL,
)
from .heating_model import (
    ForecastPoint,
    PredictionResult,
    compute_reach,
    compute_start,
    parse_heat_rates,
    parse_preset_temperatures,
)

_LOGGER = logging.getLogger(__name__)

FORECAST_TYPES = ("hourly", "twice_daily", "daily")


def make_store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    """The entry's store, holding the trigger guard of every room."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


class ForecastCoordinator(DataUpdateCoordinator[list[ForecastPoint]]):
    """Fetch the outdoor forecast shared by all rooms of an entry."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the forecast coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title} forecast",
            update_interval=UPDATE_INTERVAL,
        )
        self.forecast_type: str | None = None

    async def _async_update_data(self) -> list[ForecastPoint]:
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


class WarmWelcomeCoordinator(DataUpdateCoordinator[PredictionResult | None]):
    """Recompute one room's heating start time and fire the configured action."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        forecast_coordinator: ForecastCoordinator,
        store: Store[dict[str, Any]],
        triggered: dict[str, str],
    ) -> None:
        """Initialize the coordinator for one room subentry.

        Refreshes are driven by the forecast coordinator (which polls
        every 30 minutes) and by source entity changes, so no own update
        interval is needed. ``triggered`` is the shared trigger guard map
        (subentry id -> arrival isoformat) persisted in ``store``.
        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {subentry.title}",
            update_interval=None,
        )
        self.subentry = subentry
        self.forecast_coordinator = forecast_coordinator
        # Shared entities from the entry, room settings from the subentry.
        self.settings: dict[str, Any] = {**entry.options, **subentry.data}
        self._store = store
        self._triggered = triggered
        self.arrival: datetime | None = None
        self.current_temperature: float | None = None
        # Effective prediction target, derived from the set temperature
        # and the set preset (see _prediction_target).
        self.target_temperature: float | None = None
        # When the room is predicted to actually reach the target, and
        # whether that misses the arrival (see _async_update_data).
        self.target_reached: datetime | None = None
        self.target_at_risk: bool = False
        self.triggered_for: str | None = triggered.get(subentry.subentry_id)
        self._unsub_trigger: CALLBACK_TYPE | None = None

    @property
    def forecast_type(self) -> str | None:
        """The forecast resolution the prediction is based on."""
        return self.forecast_coordinator.forecast_type

    @callback
    def cancel_trigger(self) -> None:
        """Cancel a scheduled heating start."""
        if self._unsub_trigger is not None:
            self._unsub_trigger()
            self._unsub_trigger = None

    async def _async_update_data(self) -> PredictionResult | None:
        options = self.settings
        self.arrival = arrival = self._compute_arrival()
        if arrival is None or arrival <= dt_util.utcnow():
            # No (future) vacation end configured: idle.
            self.current_temperature = None
            self.target_temperature = None
            self.target_reached = None
            self.target_at_risk = False
            self.cancel_trigger()
            return None

        current_temp = self._current_temperature()
        if current_temp is None:
            raise UpdateFailed(
                f"No current temperature available from {options[CONF_CLIMATE_ENTITY]}"
            )
        self.current_temperature = current_temp
        self.target_temperature = target_temp = self._prediction_target()

        forecast = self.forecast_coordinator.data
        if not forecast:
            raise UpdateFailed("No outdoor forecast available yet")

        rates = parse_heat_rates(options[CONF_HEAT_RATES])
        result = compute_start(
            arrival,
            current_temp,
            target_temp,
            forecast,
            rates,
            max_lookback=MAX_LOOKBACK,
        )
        # When the required start is already in the past (the forecast
        # worsened, or the heating runs behind the model), the heating
        # can only run from now on — predict when the target is actually
        # reached and flag the room if that misses the arrival.
        self.target_reached = reached = compute_reach(
            max(result.start, dt_util.utcnow()),
            current_temp,
            target_temp,
            forecast,
            rates,
            max_lookahead=MAX_LOOKBACK,
        )
        self.target_at_risk = reached is None or reached > arrival + LATE_TOLERANCE
        self._schedule_trigger(result.start, arrival)
        return result

    def _prediction_target(self) -> float:
        """Temperature the room is expected to reach.

        When the temperature is set explicitly it wins (it is sent after
        the preset and overrides its setpoint). A preset-only action heats
        to the preset's own setpoint, which cannot be read from the climate
        entity; use the configured preset temperature map and fall back to
        the target temperature.
        """
        options = self.settings
        if not options.get(CONF_SET_TEMPERATURE) and options.get(CONF_SET_PRESET):
            presets = parse_preset_temperatures(
                options.get(CONF_PRESET_TEMPERATURES) or []
            )
            target = presets.get(options.get(CONF_TARGET_PRESET, ""))
            if target is not None:
                return target
        return float(options[CONF_TARGET_TEMPERATURE])

    def _compute_arrival(self) -> datetime | None:
        """Arrival datetime from the end date entity.

        Naive values are interpreted in Home Assistant's local time zone;
        date-only values (an input_datetime without time) fall back to
        midnight.
        """
        options = self.settings
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
        state = self.hass.states.get(self.settings[CONF_CLIMATE_ENTITY])
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        current = state.attributes.get("current_temperature")
        if current is None:
            return None
        return float(current)

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

        options = self.settings
        entity_id = options[CONF_CLIMATE_ENTITY]
        set_preset = bool(options.get(CONF_SET_PRESET))
        set_temperature = bool(options.get(CONF_SET_TEMPERATURE))
        _LOGGER.info(
            "Starting pre-heat of %s for arrival at %s (set preset: %s, "
            "set temperature: %s)",
            entity_id,
            arrival,
            set_preset,
            set_temperature,
        )
        try:
            preset_sent = False
            if set_preset:
                # The preset can be missing if set_preset was enabled via
                # the config entity without one configured.
                if preset := options.get(CONF_TARGET_PRESET):
                    await self.hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": entity_id, "preset_mode": preset},
                        blocking=True,
                    )
                    preset_sent = True
                else:
                    _LOGGER.warning(
                        "No preset configured for %s; skipping set_preset_mode",
                        entity_id,
                    )
            if set_temperature:
                if preset_sent:
                    # Give the climate entity time to apply the preset so
                    # the explicit temperature overrides its setpoint.
                    await asyncio.sleep(TRIGGER_SETTLE_DELAY)
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
        self._triggered[self.subentry.subentry_id] = self.triggered_for
        await self._store.async_save({"triggered_for": self._triggered})
        self.async_update_listeners()
