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
    CONF_PRESET_TEMPERATURES,
    CONF_TARGET_TEMPERATURE,
    CONF_WEATHER_ENTITY,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
    SUBENTRY_TYPE_ROOM,
)
from .heating_model import (
    format_heat_rates,
    format_preset_temperatures,
    parse_heat_rates,
    parse_preset_temperatures,
)

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
            vol.Optional(CONF_PRESET_TEMPERATURES): SelectSelector(
                SelectSelectorConfig(options=[], multiple=True, custom_value=True)
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
    try:
        presets = parse_preset_temperatures(
            user_input.get(CONF_PRESET_TEMPERATURES) or []
        )
    except ValueError:
        errors[CONF_PRESET_TEMPERATURES] = "invalid_preset_temperatures"
    else:
        user_input[CONF_PRESET_TEMPERATURES] = format_preset_temperatures(presets)
    if user_input.get(CONF_ACTION) != ACTION_SET_TEMPERATURE and not user_input.get(
        CONF_PRESET_MODE
    ):
        errors[CONF_PRESET_MODE] = "preset_mode_required"
    return errors


class VacationHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: the entities shared by all rooms."""

    VERSION = 1

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
