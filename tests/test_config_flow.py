"""Tests for the config, options, and room subentry flows."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER, ConfigSubentryData
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vacation_heating.config_flow import settings_schema
from custom_components.vacation_heating.const import (
    CONF_ACTION,
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_PRESET_MODE,
    CONF_PRESET_TEMPERATURES,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    SUBENTRY_TYPE_ROOM,
)

SHARED_INPUT = {
    CONF_WEATHER_ENTITY: "weather.home",
    CONF_END_DATE_ENTITY: "input_datetime.vacation_end",
}

ROOM_INPUT = {
    CONF_NAME: "Living Room",
    CONF_CLIMATE_ENTITY: "climate.living_room",
}

HEAT_RATES_INPUT = [
    {"outdoor_temp": 10, "gain": 3.5, "hours": 5},
    {"outdoor_temp": -10, "gain": 1, "hours": 5},
]

PRESET_TEMPERATURES_INPUT = [
    {"preset": "comfort", "temperature": 21.0},
    {"preset": "eco", "temperature": 17.5},
]

SETTINGS_INPUT = {
    CONF_TARGET_TEMPERATURE: 21.0,
    CONF_HEAT_RATES: HEAT_RATES_INPUT,
    CONF_ACTION: "both",
    CONF_PRESET_MODE: "comfort",
    CONF_PRESET_TEMPERATURES: PRESET_TEMPERATURES_INPUT,
}

ROOM_DATA = {
    CONF_CLIMATE_ENTITY: "climate.living_room",
    CONF_TARGET_TEMPERATURE: 21.0,
    # Sorted by outdoor temperature on save.
    CONF_HEAT_RATES: [HEAT_RATES_INPUT[1], HEAT_RATES_INPUT[0]],
    CONF_ACTION: "both",
    CONF_PRESET_MODE: "comfort",
    CONF_PRESET_TEMPERATURES: PRESET_TEMPERATURES_INPUT,
}


def patch_setup():
    return patch(
        "custom_components.vacation_heating.async_setup_entry", return_value=True
    )


def patch_unload():
    return patch(
        "custom_components.vacation_heating.async_unload_entry", return_value=True
    )


async def make_entry(hass: HomeAssistant, with_room: bool = False) -> MockConfigEntry:
    """Add a set-up parent entry, optionally with one room subentry."""
    subentries = (
        [
            ConfigSubentryData(
                data=ROOM_DATA,
                subentry_type=SUBENTRY_TYPE_ROOM,
                title="Living Room",
                unique_id=None,
            )
        ]
        if with_room
        else []
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vacation Heating",
        data={},
        options=SHARED_INPUT,
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """The initial flow only asks for the shared entities."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SHARED_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Vacation Heating"
    assert result["data"] == {}
    assert result["options"] == SHARED_INPUT


async def test_second_entry_aborts(hass: HomeAssistant) -> None:
    """Only a single instance is allowed; rooms are added as subentries."""
    with patch_setup(), patch_unload():
        await make_entry(hass)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_add_room_subentry(hass: HomeAssistant) -> None:
    """The room flow walks both steps and stores normalized settings."""
    with patch_setup(), patch_unload():
        entry = await make_entry(hass)

        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_ROOM), context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], ROOM_INPUT
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "settings"

        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], SETTINGS_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_TYPE_ROOM
    assert subentry.title == "Living Room"
    assert dict(subentry.data) == ROOM_DATA
    assert CONF_NAME not in subentry.data


async def test_settings_schema_offers_entity_presets(hass: HomeAssistant) -> None:
    """The preset dropdown lists the selected climate entity's presets."""
    hass.states.async_set(
        "climate.living_room", "heat", {"preset_modes": ["eco", "comfort", "boost"]}
    )
    schema = settings_schema(hass, "climate.living_room")
    preset_selector = schema.schema[CONF_PRESET_MODE]
    assert preset_selector.config["options"] == ["eco", "comfort", "boost"]
    assert preset_selector.config["custom_value"] is True

    # Unknown entity: empty dropdown, custom values still allowed.
    schema = settings_schema(hass, "climate.missing")
    assert schema.schema[CONF_PRESET_MODE].config["options"] == []


async def test_settings_schema_follows_unit_system(hass: HomeAssistant) -> None:
    """Temperature fields use HA's configured unit system."""
    schema = settings_schema(hass, "climate.missing")
    target = schema.schema[CONF_TARGET_TEMPERATURE]
    assert target.config["unit_of_measurement"] == "°C"
    assert (target.config["min"], target.config["max"]) == (5, 35)

    hass.config.units = US_CUSTOMARY_SYSTEM
    schema = settings_schema(hass, "climate.missing")
    target = schema.schema[CONF_TARGET_TEMPERATURE]
    assert target.config["unit_of_measurement"] == "°F"
    assert (target.config["min"], target.config["max"]) == (40, 95)
    rate_fields = schema.schema[CONF_HEAT_RATES].config["fields"]
    outdoor = rate_fields["outdoor_temp"]["selector"]["number"]
    assert outdoor["unit_of_measurement"] == "°F"


async def test_room_flow_rejects_invalid_settings(hass: HomeAssistant) -> None:
    """Malformed pairs and a missing preset keep the settings form open."""
    with patch_setup(), patch_unload():
        entry = await make_entry(hass)
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_ROOM), context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], ROOM_INPUT
        )

        settings = {
            **SETTINGS_INPUT,
            # Invalid: no point with a positive gain, duplicate preset.
            CONF_HEAT_RATES: [{"outdoor_temp": 0, "gain": -1, "hours": 2}],
            CONF_PRESET_TEMPERATURES: [
                {"preset": "eco", "temperature": 17},
                {"preset": "eco", "temperature": 18},
            ],
            CONF_ACTION: "set_preset",
        }
        del settings[CONF_PRESET_MODE]
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], settings
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    assert result["errors"] == {
        CONF_HEAT_RATES: "invalid_heat_rates",
        CONF_PRESET_TEMPERATURES: "invalid_preset_temperatures",
        CONF_PRESET_MODE: "preset_mode_required",
    }


async def test_reconfigure_room(hass: HomeAssistant) -> None:
    """Reconfiguring a room updates its title, entity, and settings."""
    with patch_setup(), patch_unload():
        entry = await make_entry(hass, with_room=True)
        subentry_id = next(iter(entry.subentries))

        result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {CONF_NAME: "Bedroom", CONF_CLIMATE_ENTITY: "climate.bedroom"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "settings"

        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**SETTINGS_INPUT, CONF_PRESET_MODE: "eco"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = entry.subentries[subentry_id]
    assert subentry.title == "Bedroom"
    assert subentry.data[CONF_CLIMATE_ENTITY] == "climate.bedroom"
    assert subentry.data[CONF_PRESET_MODE] == "eco"


async def test_options_flow_updates_shared_entities(hass: HomeAssistant) -> None:
    """The options flow edits the shared weather and end date entities."""
    with patch_setup(), patch_unload():
        entry = await make_entry(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {**SHARED_INPUT, CONF_WEATHER_ENTITY: "weather.forecast_home"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_WEATHER_ENTITY] == "weather.forecast_home"
    assert entry.options[CONF_END_DATE_ENTITY] == "input_datetime.vacation_end"
