"""Tests for the config, options, and reconfigure flows."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vacation_heating.config_flow import settings_schema
from custom_components.vacation_heating.const import (
    CONF_ACTION,
    CONF_ARRIVAL_TIME,
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_PRESET_MODE,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)

ENTITY_INPUT = {
    CONF_CLIMATE_ENTITY: "climate.living_room",
    CONF_WEATHER_ENTITY: "weather.home",
    CONF_END_DATE_ENTITY: "input_datetime.vacation_end",
}

SETTINGS_INPUT = {
    CONF_ARRIVAL_TIME: "12:00:00",
    CONF_TARGET_TEMPERATURE: 21.0,
    CONF_HEAT_RATES: ["10: 0.7", "-10: 0.2"],
    CONF_ACTION: "both",
    CONF_PRESET_MODE: "comfort",
}

VALID_OPTIONS = {**ENTITY_INPUT, **SETTINGS_INPUT}


def patch_setup():
    return patch(
        "custom_components.vacation_heating.async_setup_entry", return_value=True
    )


def patch_unload():
    return patch(
        "custom_components.vacation_heating.async_unload_entry", return_value=True
    )


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """The happy path walks both steps and creates a sorted-options entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Living Room", **ENTITY_INPUT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"

    with patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SETTINGS_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room"
    assert result["data"] == {}
    assert result["options"][CONF_HEAT_RATES] == ["-10: 0.2", "10: 0.7"]
    assert result["options"][CONF_PRESET_MODE] == "comfort"
    assert CONF_NAME not in result["options"]


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


async def test_user_flow_rejects_invalid_heat_rates(hass: HomeAssistant) -> None:
    """Malformed heat rate pairs keep the settings form open with an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Living Room", **ENTITY_INPUT}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**SETTINGS_INPUT, CONF_HEAT_RATES: ["banana"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    assert result["errors"] == {CONF_HEAT_RATES: "invalid_heat_rates"}


async def test_user_flow_requires_preset_for_preset_actions(hass: HomeAssistant) -> None:
    """A preset must be chosen unless the action is temperature-only."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Living Room", **ENTITY_INPUT}
    )
    settings = {**SETTINGS_INPUT, CONF_ACTION: "set_preset"}
    del settings[CONF_PRESET_MODE]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], settings
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PRESET_MODE: "preset_mode_required"}


async def test_options_flow_updates_and_sorts(hass: HomeAssistant) -> None:
    """The options flow updates every setting and normalizes heat rates."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Living Room", data={}, options=VALID_OPTIONS
    )
    entry.add_to_hass(hass)
    with patch_setup(), patch_unload():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], ENTITY_INPUT
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "settings"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                **SETTINGS_INPUT,
                CONF_TARGET_TEMPERATURE: 22.5,
                CONF_HEAT_RATES: ["5: 0.5", "-5: 0.3"],
                CONF_ACTION: "set_temperature",
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TARGET_TEMPERATURE] == 22.5
    assert entry.options[CONF_HEAT_RATES] == ["-5: 0.3", "5: 0.5"]
    assert entry.options[CONF_ACTION] == "set_temperature"


async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Reconfiguring updates the title, entities, and settings."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Living Room", data={}, options=VALID_OPTIONS
    )
    entry.add_to_hass(hass)
    with patch_setup(), patch_unload():
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Bedroom",
                **ENTITY_INPUT,
                CONF_CLIMATE_ENTITY: "climate.bedroom",
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "settings"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**SETTINGS_INPUT, CONF_PRESET_MODE: "eco"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Bedroom"
    assert entry.options[CONF_CLIMATE_ENTITY] == "climate.bedroom"
    assert entry.options[CONF_PRESET_MODE] == "eco"
