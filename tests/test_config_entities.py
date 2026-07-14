"""Tests for the config entities exposing the room settings."""

from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vacation_heating.const import (
    CONF_ACTION,
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_PRESET_MODE,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    SUBENTRY_TYPE_ROOM,
)

NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
ARRIVAL = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

ROOM_DATA = {
    CONF_CLIMATE_ENTITY: "climate.living_room",
    CONF_TARGET_TEMPERATURE: 21.0,
    # 1°C gained in 2 h at 0°C outdoors = 0.5°C/h.
    CONF_HEAT_RATES: [{"outdoor_temp": 0, "gain": 1, "hours": 2}],
    CONF_ACTION: "both",
    CONF_PRESET_MODE: "comfort",
}


async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    await hass.config.async_set_time_zone("UTC")
    hass.states.async_set(
        "climate.living_room",
        "off",
        {"current_temperature": 15.0, "preset_modes": ["eco", "comfort"]},
    )
    hass.states.async_set("weather.home", "sunny")
    hass.states.async_set("input_datetime.vacation_end", "2026-07-20 12:00:00")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vacation Heating",
        data={},
        options={
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_END_DATE_ENTITY: "input_datetime.vacation_end",
        },
        subentries_data=[
            ConfigSubentryData(
                data=ROOM_DATA,
                subentry_type=SUBENTRY_TYPE_ROOM,
                title="Living Room",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def room_data(entry: MockConfigEntry) -> dict:
    return dict(next(iter(entry.subentries.values())).data)


async def test_config_entities_expose_settings(hass, freezer, forecast_calls) -> None:
    """Each room gets a number and two selects reflecting its settings."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    target = hass.states.get("number.living_room_target_temperature")
    assert float(target.state) == 21.0

    action = hass.states.get("select.living_room_action_at_heating_start")
    assert action.state == "both"
    assert action.attributes["options"] == ["set_preset", "set_temperature", "both"]

    preset = hass.states.get("select.living_room_preset_to_set")
    assert preset.state == "comfort"
    assert preset.attributes["options"] == ["eco", "comfort"]


async def test_target_temperature_updates_room_and_prediction(
    hass, freezer, forecast_calls
) -> None:
    """Setting the number persists into the subentry and recomputes the start."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.living_room_target_temperature", "value": 23.0},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert room_data(entry)[CONF_TARGET_TEMPERATURE] == 23.0
    # Deficit 23 - 15 = 8°C at 0.5°C/h -> 16 h pre-heat after the reload.
    state = hass.states.get("sensor.living_room_heating_start")
    assert dt_util.parse_datetime(state.state) == ARRIVAL - timedelta(hours=16)


async def test_action_select_updates_room(hass, freezer, forecast_calls) -> None:
    """Selecting an action persists into the subentry."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)

    await hass.services.async_call(
        "select",
        "select_option",
        {
            "entity_id": "select.living_room_action_at_heating_start",
            "option": "set_temperature",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert room_data(entry)[CONF_ACTION] == "set_temperature"
    state = hass.states.get("select.living_room_action_at_heating_start")
    assert state.state == "set_temperature"


async def test_preset_select_updates_room(hass, freezer, forecast_calls) -> None:
    """Selecting a preset persists into the subentry."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.living_room_preset_to_set", "option": "eco"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert room_data(entry)[CONF_PRESET_MODE] == "eco"
    state = hass.states.get("select.living_room_preset_to_set")
    assert state.state == "eco"


async def test_preset_select_keeps_unknown_configured_preset(
    hass, freezer, forecast_calls
) -> None:
    """A configured preset the climate entity no longer offers stays selectable."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    hass.states.async_set(
        "climate.living_room",
        "off",
        {"current_temperature": 15.0, "preset_modes": ["away"]},
    )
    freezer.tick(timedelta(seconds=15))
    await hass.async_block_till_done()

    preset = hass.states.get("select.living_room_preset_to_set")
    assert preset.state == "comfort"
    assert preset.attributes["options"] == ["away", "comfort"]
