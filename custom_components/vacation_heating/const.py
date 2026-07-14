"""Constants for the Vacation Heating integration."""

from datetime import timedelta

DOMAIN = "vacation_heating"

SUBENTRY_TYPE_ROOM = "room"

# Dispatcher signal fired on every prediction or forecast update; feeds
# the websocket subscriptions of the bundled Lovelace card.
SIGNAL_UPDATE = f"{DOMAIN}_updated"

CONF_CLIMATE_ENTITY = "climate_entity"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_END_DATE_ENTITY = "end_date_entity"
CONF_TARGET_TEMPERATURE = "target_temperature"
CONF_HEAT_RATES = "heat_rates"
CONF_ACTION = "action"
CONF_PRESET_MODE = "preset_mode"
CONF_PRESET_TEMPERATURES = "preset_temperatures"

ACTION_SET_PRESET = "set_preset"
ACTION_SET_TEMPERATURE = "set_temperature"
ACTION_BOTH = "both"
ACTIONS = [ACTION_SET_PRESET, ACTION_SET_TEMPERATURE, ACTION_BOTH]

DEFAULT_TARGET_TEMPERATURE = 21.0
DEFAULT_TARGET_TEMPERATURE_F = 70.0
TARGET_TEMPERATURE_RANGE_C = (5.0, 35.0)
TARGET_TEMPERATURE_RANGE_F = (40.0, 95.0)

UPDATE_INTERVAL = timedelta(minutes=30)

# How far back from the arrival time we are willing to extrapolate before
# giving up and starting the heating immediately.
MAX_LOOKBACK = timedelta(days=14)

STORAGE_VERSION = 1

ATTR_PREHEAT_HOURS = "required_preheat_hours"
ATTR_DEFICIT = "temperature_deficit"
ATTR_BEYOND_FORECAST = "beyond_forecast"
ATTR_FORECAST_TYPE = "forecast_type"
ATTR_ARRIVAL = "arrival"
ATTR_TRIGGERED_FOR = "triggered_for"
ATTR_PREDICTED_TEMPERATURES = "predicted_temperatures"
ATTR_FORECAST = "forecast"
