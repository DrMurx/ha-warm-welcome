"""Config flow for the Vacation Heating integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
import voluptuous as vol

from .const import (
    ACTION_BOTH,
    ACTION_SET_TEMPERATURE,
    ACTIONS,
    CONF_ACTION,
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_PRESET_MODE,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
)
from .heating_model import format_heat_rates, parse_heat_rates

ENTITY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIMATE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="climate")
        ),
        vol.Required(CONF_WEATHER_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="weather")
        ),
        vol.Required(CONF_END_DATE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=["input_datetime", "datetime"])
        ),
    }
)

NAMED_ENTITY_SCHEMA = vol.Schema(
    {vol.Required(CONF_NAME): TextSelector()}
).extend(ENTITY_SCHEMA.schema)


def settings_schema(hass: HomeAssistant, climate_entity_id: str) -> vol.Schema:
    """Build the settings form, with presets read from the climate entity.

    The preset dropdown offers the entity's currently advertised presets;
    custom values stay allowed so the flow also works while the entity is
    unavailable.
    """
    presets: list[str] = []
    if (state := hass.states.get(climate_entity_id)) is not None:
        presets = [str(preset) for preset in state.attributes.get("preset_modes") or []]

    return vol.Schema(
        {
            vol.Required(CONF_HEAT_RATES): SelectSelector(
                SelectSelectorConfig(options=[], multiple=True, custom_value=True)
            ),
            vol.Required(CONF_ACTION, default=ACTION_BOTH): SelectSelector(
                SelectSelectorConfig(
                    options=ACTIONS,
                    translation_key="action",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_PRESET_MODE): SelectSelector(
                SelectSelectorConfig(
                    options=presets,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_TARGET_TEMPERATURE, default=DEFAULT_TARGET_TEMPERATURE
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5,
                    max=35,
                    step=0.5,
                    unit_of_measurement="°C",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _validate_and_normalize(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate settings input in place; return form errors.

    On success the heat rate list is replaced with its canonical sorted
    form so re-opened forms show the pairs in order.
    """
    errors: dict[str, str] = {}
    try:
        rates = parse_heat_rates(user_input.get(CONF_HEAT_RATES, []))
    except ValueError:
        errors[CONF_HEAT_RATES] = "invalid_heat_rates"
    else:
        user_input[CONF_HEAT_RATES] = format_heat_rates(rates)
    if user_input.get(CONF_ACTION) != ACTION_SET_TEMPERATURE and not user_input.get(
        CONF_PRESET_MODE
    ):
        errors[CONF_PRESET_MODE] = "preset_mode_required"
    return errors


class VacationHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial and reconfigure flows."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._entity_input: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: name and source entities."""
        if user_input is not None:
            self._entity_input = user_input
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                NAMED_ENTITY_SCHEMA, user_input
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First reconfigure step: name and source entities, prefilled."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self._entity_input = user_input
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                NAMED_ENTITY_SCHEMA, {CONF_NAME: entry.title, **entry.options}
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Second step: schedule, heat rates, and the action to perform."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_and_normalize(user_input)
            if not errors:
                options = {**self._entity_input, **user_input}
                name = options.pop(CONF_NAME)
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(), title=name, options=options
                    )
                return self.async_create_entry(title=name, data={}, options=options)

        suggested = user_input
        if suggested is None and self.source == SOURCE_RECONFIGURE:
            suggested = dict(self._get_reconfigure_entry().options)
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                settings_schema(self.hass, self._entity_input[CONF_CLIMATE_ENTITY]),
                suggested,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VacationHeatingOptionsFlow:
        """Return the options flow handler."""
        return VacationHeatingOptionsFlow()


class VacationHeatingOptionsFlow(OptionsFlowWithReload):
    """Allow changing every setting after setup."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._entity_input: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: source entities."""
        if user_input is not None:
            self._entity_input = user_input
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                ENTITY_SCHEMA, self.config_entry.options
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Second step: schedule, heat rates, and the action to perform."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_and_normalize(user_input)
            if not errors:
                return self.async_create_entry(
                    data={**self._entity_input, **user_input}
                )

        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                settings_schema(self.hass, self._entity_input[CONF_CLIMATE_ENTITY]),
                user_input or self.config_entry.options,
            ),
            errors=errors,
        )
