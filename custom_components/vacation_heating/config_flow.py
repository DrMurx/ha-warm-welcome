"""Config flow for the Vacation Heating integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
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
    TimeSelector,
)
import voluptuous as vol

from .const import (
    ACTION_BOTH,
    ACTION_SET_TEMPERATURE,
    ACTIONS,
    CONF_ACTION,
    CONF_ARRIVAL_TIME,
    CONF_CLIMATE_ENTITY,
    CONF_END_DATE_ENTITY,
    CONF_HEAT_RATES,
    CONF_HVAC_MODE,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DEFAULT_ARRIVAL_TIME,
    DEFAULT_HVAC_MODE,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
)
from .heating_model import format_heat_rates, parse_heat_rates

HVAC_MODES = ["heat", "auto", "heat_cool"]

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIMATE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="climate")
        ),
        vol.Required(CONF_WEATHER_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="weather")
        ),
        vol.Required(CONF_END_DATE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=["input_datetime", "date", "datetime"])
        ),
        vol.Required(CONF_ARRIVAL_TIME, default=DEFAULT_ARRIVAL_TIME): TimeSelector(),
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
        vol.Optional(CONF_HVAC_MODE, default=DEFAULT_HVAC_MODE): SelectSelector(
            SelectSelectorConfig(
                options=HVAC_MODES,
                translation_key="hvac_mode",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {vol.Required(CONF_NAME): TextSelector()}
).extend(OPTIONS_SCHEMA.schema)


def _validate_and_normalize(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate user input in place; return form errors.

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
        CONF_HVAC_MODE
    ):
        errors[CONF_HVAC_MODE] = "hvac_mode_required"
    return errors


class VacationHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial and reconfigure flows."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a new vacation heating entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_and_normalize(user_input)
            if not errors:
                name = user_input.pop(CONF_NAME)
                return self.async_create_entry(title=name, data={}, options=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(CONFIG_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure an existing entry, including its name."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_and_normalize(user_input)
            if not errors:
                name = user_input.pop(CONF_NAME)
                return self.async_update_reload_and_abort(
                    entry, title=name, options=user_input
                )

        suggested = user_input or {CONF_NAME: entry.title, **entry.options}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(CONFIG_SCHEMA, suggested),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VacationHeatingOptionsFlow:
        """Return the options flow handler."""
        return VacationHeatingOptionsFlow()


class VacationHeatingOptionsFlow(OptionsFlowWithReload):
    """Allow changing every setting after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_and_normalize(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )
