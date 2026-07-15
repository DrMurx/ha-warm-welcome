"""Config flow for the Vacation Heating integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    ObjectSelectorConfig,
    ObjectSelectorField,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
import voluptuous as vol

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
    DEFAULT_TARGET_TEMPERATURE,
    DEFAULT_TARGET_TEMPERATURE_F,
    DOMAIN,
    SUBENTRY_TYPE_ROOM,
    TARGET_TEMPERATURE_RANGE_C,
    TARGET_TEMPERATURE_RANGE_F,
)
from .heating_model import parse_heat_rates, parse_preset_temperatures

SHARED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_WEATHER_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="weather")
        ),
        vol.Required(CONF_END_DATE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=["input_datetime", "datetime"])
        ),
    }
)

ROOM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_CLIMATE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="climate")
        ),
    }
)


def _temperature_number(
    unit: str, min_value: float | None = None, max_value: float | None = None
) -> NumberSelector:
    config = NumberSelectorConfig(
        step=0.5, unit_of_measurement=unit, mode=NumberSelectorMode.BOX
    )
    if min_value is not None:
        config["min"] = min_value
    if max_value is not None:
        config["max"] = max_value
    return NumberSelector(config)


def settings_schema(hass: HomeAssistant, climate_entity_id: str) -> vol.Schema:
    """Build the settings form, with presets read from the climate entity.

    The preset dropdown offers the entity's currently advertised presets;
    custom values stay allowed so the flow also works while the entity is
    unavailable. Temperature fields follow Home Assistant's unit system.
    """
    presets: list[str] = []
    if (state := hass.states.get(climate_entity_id)) is not None:
        presets = [str(preset) for preset in state.attributes.get("preset_modes") or []]

    unit = hass.config.units.temperature_unit
    fahrenheit = unit == UnitOfTemperature.FAHRENHEIT
    target_default = (
        DEFAULT_TARGET_TEMPERATURE_F if fahrenheit else DEFAULT_TARGET_TEMPERATURE
    )
    target_min, target_max = (
        TARGET_TEMPERATURE_RANGE_F if fahrenheit else TARGET_TEMPERATURE_RANGE_C
    )

    # Object selector field labels are plain strings (not translatable);
    # they carry the unit dynamically. Field selectors must be given in
    # dict form: ObjectSelector validation cannot handle instances.
    def _temperature_field(**extra: Any) -> dict[str, Any]:
        return {"number": {"step": 0.5, "unit_of_measurement": unit, "mode": "box", **extra}}

    heat_rate_fields = {
        "outdoor_temp": ObjectSelectorField(
            required=True,
            label=f"Outdoor temperature ({unit})",
            selector=_temperature_field(),
        ),
        "gain": ObjectSelectorField(
            required=True,
            label=f"Temperature gain ({unit}, negative if the heating cannot keep up)",
            selector=_temperature_field(step=0.1),
        ),
        "hours": ObjectSelectorField(
            required=True,
            label="Measured over (hours)",
            selector={
                "number": {"min": 0.5, "step": 0.5, "unit_of_measurement": "h", "mode": "box"}
            },
        ),
    }
    preset_temperature_fields = {
        "preset": ObjectSelectorField(
            required=True,
            label="Preset",
            selector={
                "select": {"options": presets, "custom_value": True, "mode": "dropdown"}
            },
        ),
        "temperature": ObjectSelectorField(
            required=True,
            label=f"Temperature ({unit})",
            selector=_temperature_field(min=target_min, max=target_max),
        ),
    }

    return vol.Schema(
        {
            vol.Required(CONF_HEAT_RATES): ObjectSelector(
                ObjectSelectorConfig(
                    multiple=True,
                    label_field="outdoor_temp",
                    description_field="gain",
                    fields=heat_rate_fields,
                )
            ),
            vol.Required(CONF_SET_PRESET, default=True): BooleanSelector(),
            vol.Optional(CONF_TARGET_PRESET): SelectSelector(
                SelectSelectorConfig(
                    options=presets,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_PRESET_TEMPERATURES): ObjectSelector(
                ObjectSelectorConfig(
                    multiple=True,
                    label_field="preset",
                    description_field="temperature",
                    fields=preset_temperature_fields,
                )
            ),
            vol.Required(CONF_SET_TEMPERATURE, default=True): BooleanSelector(),
            vol.Required(
                CONF_TARGET_TEMPERATURE, default=target_default
            ): _temperature_number(unit, target_min, target_max),
        }
    )


def _validate_and_normalize(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate settings input in place; return form errors.

    On success the heat rate points are sorted by outdoor temperature so
    re-opened forms show them in order.
    """
    errors: dict[str, str] = {}
    try:
        parse_heat_rates(user_input.get(CONF_HEAT_RATES) or [])
    except ValueError:
        errors[CONF_HEAT_RATES] = "invalid_heat_rates"
    else:
        user_input[CONF_HEAT_RATES] = sorted(
            user_input[CONF_HEAT_RATES], key=lambda entry: float(entry["outdoor_temp"])
        )
    try:
        parse_preset_temperatures(user_input.get(CONF_PRESET_TEMPERATURES) or [])
    except ValueError:
        errors[CONF_PRESET_TEMPERATURES] = "invalid_preset_temperatures"
    else:
        user_input.setdefault(CONF_PRESET_TEMPERATURES, [])
    if not user_input.get(CONF_SET_PRESET) and not user_input.get(CONF_SET_TEMPERATURE):
        errors["base"] = "no_action"
    if user_input.get(CONF_SET_PRESET) and not user_input.get(CONF_TARGET_PRESET):
        errors[CONF_TARGET_PRESET] = "target_preset_required"
    return errors


class VacationHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: the entities shared by all rooms."""

    VERSION = 1
    # Minor version 2: room action select replaced by the set_preset and
    # set_temperature booleans; minor version 3: the preset_mode key
    # renamed to target_preset (both migrated in async_migrate_entry).
    MINOR_VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the shared weather and vacation end entities."""
        if user_input is not None:
            return self.async_create_entry(
                title="Vacation Heating", data={}, options=user_input
            )

        return self.async_show_form(step_id="user", data_schema=SHARED_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VacationHeatingOptionsFlow:
        """Return the options flow handler."""
        return VacationHeatingOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Rooms are managed as subentries."""
        return {SUBENTRY_TYPE_ROOM: RoomSubentryFlow}


class VacationHeatingOptionsFlow(OptionsFlow):
    """Allow changing the shared entities after setup.

    A plain options flow: the entry's update listener performs the reload
    (it must exist anyway to apply subentry changes).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the shared entities."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                SHARED_SCHEMA, self.config_entry.options
            ),
        )


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a room."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._room_input: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """First step: room name and climate entity."""
        if user_input is not None:
            self._room_input = user_input
            return await self.async_step_settings()

        return self.async_show_form(step_id="user", data_schema=ROOM_SCHEMA)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """First reconfigure step: room name and climate entity, prefilled."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            self._room_input = user_input
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                ROOM_SCHEMA, {CONF_NAME: subentry.title, **subentry.data}
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Second step: heat rates and the action to perform."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_and_normalize(user_input)
            if not errors:
                data = {**self._room_input, **user_input}
                name = data.pop(CONF_NAME)
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        title=name,
                        data=data,
                    )
                return self.async_create_entry(title=name, data=data)

        suggested = user_input
        if suggested is None and self.source == SOURCE_RECONFIGURE:
            suggested = dict(self._get_reconfigure_subentry().data)
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                settings_schema(self.hass, self._room_input[CONF_CLIMATE_ENTITY]),
                suggested,
            ),
            errors=errors,
        )
