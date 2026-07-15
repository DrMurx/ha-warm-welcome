"""Tests for the config entities exposing the room settings."""

from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vacation_heating.const import (
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_SET_PRESET,
    CONF_SET_TEMPERATURE,
    CONF_TARGET_PRESET,
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
    CONF_SET_PRESET: True,
    CONF_SET_TEMPERATURE: True,
    CONF_TARGET_PRESET: "comfort",
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
    """Each room gets a number, a preset select, and two action switches."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    target = hass.states.get("number.living_room_vacation_heating_target_temperature")
    assert float(target.state) == 21.0

    set_preset = hass.states.get("switch.living_room_vacation_heating_use_preset")
    assert set_preset.state == "on"
    set_temperature = hass.states.get(
        "switch.living_room_vacation_heating_use_temperature"
    )
    assert set_temperature.state == "on"

    preset = hass.states.get("select.living_room_vacation_heating_target_preset")
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
        {"entity_id": "number.living_room_vacation_heating_target_temperature", "value": 23.0},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert room_data(entry)[CONF_TARGET_TEMPERATURE] == 23.0
    # Deficit 23 - 15 = 8°C at 0.5°C/h -> 16 h pre-heat after the reload.
    state = hass.states.get("sensor.living_room_heating_start")
    assert dt_util.parse_datetime(state.state) == ARRIVAL - timedelta(hours=16)


async def test_action_switch_updates_room(hass, freezer, forecast_calls) -> None:
    """Toggling an action switch persists into the subentry."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.living_room_vacation_heating_use_preset"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert room_data(entry)[CONF_SET_PRESET] is False
    assert room_data(entry)[CONF_SET_TEMPERATURE] is True
    state = hass.states.get("switch.living_room_vacation_heating_use_preset")
    assert state.state == "off"


async def test_dependent_entities_unavailable_while_toggle_off(
    hass, freezer, forecast_calls
) -> None:
    """The preset select and temperature number gray out with their toggle."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    for toggle, dependent in (
        (
            "switch.living_room_vacation_heating_use_preset",
            "select.living_room_vacation_heating_target_preset",
        ),
        (
            "switch.living_room_vacation_heating_use_temperature",
            "number.living_room_vacation_heating_target_temperature",
        ),
    ):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": toggle}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(dependent).state == "unavailable"

        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": toggle}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(dependent).state != "unavailable"


async def test_preset_select_updates_room(hass, freezer, forecast_calls) -> None:
    """Selecting a preset persists into the subentry."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.living_room_vacation_heating_target_preset", "option": "eco"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert room_data(entry)[CONF_TARGET_PRESET] == "eco"
    state = hass.states.get("select.living_room_vacation_heating_target_preset")
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

    preset = hass.states.get("select.living_room_vacation_heating_target_preset")
    assert preset.state == "comfort"
    assert preset.attributes["options"] == ["away", "comfort"]
