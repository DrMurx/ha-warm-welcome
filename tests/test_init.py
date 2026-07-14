"""End-to-end tests: setup, prediction, and triggering the re-heat."""

from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

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

NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
# Vacation ends 2026-07-20 at 12:00 UTC (tests run in UTC).
ARRIVAL = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

SHARED_OPTIONS = {
    CONF_WEATHER_ENTITY: "weather.home",
    CONF_END_DATE_ENTITY: "input_datetime.vacation_end",
}

ROOM_DATA = {
    CONF_CLIMATE_ENTITY: "climate.living_room",
    CONF_TARGET_TEMPERATURE: 21.0,
    # 1°C gained in 2 h at 0°C outdoors = 0.5°C/h; 6°C deficit -> 12 h pre-heat.
    CONF_HEAT_RATES: [{"outdoor_temp": 0, "gain": 1, "hours": 2}],
    CONF_ACTION: "both",
    CONF_PRESET_MODE: "comfort",
}

EXPECTED_START = ARRIVAL - timedelta(hours=12)


@pytest.fixture
async def forecast_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Register a mock weather.get_forecasts returning a constant 0°C hourly forecast.

    The real weather integration is set up first so that its entity service
    registration does not replace this mock during config entry setup.
    """
    assert await async_setup_component(hass, "weather", {})
    calls: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> dict:
        calls.append(call)
        if call.data["type"] != "hourly":
            return {call.data["entity_id"]: {"forecast": []}}
        start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        forecast = [
            {
                "datetime": (start + timedelta(hours=i)).isoformat(),
                "temperature": 0.0,
            }
            for i in range(120)
        ]
        return {call.data["entity_id"]: {"forecast": forecast}}

    hass.services.async_register(
        "weather", "get_forecasts", handler, supports_response=SupportsResponse.ONLY
    )
    return calls


def room(title: str, data: dict | None = None) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data or ROOM_DATA,
        subentry_type=SUBENTRY_TYPE_ROOM,
        title=title,
        unique_id=None,
    )


async def setup_entry(
    hass: HomeAssistant, subentries: list[ConfigSubentryData] | None = None
) -> MockConfigEntry:
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
        options=SHARED_OPTIONS,
        subentries_data=subentries if subentries is not None else [room("Living Room")],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_sensors_expose_prediction(hass, freezer, forecast_calls) -> None:
    """The start sensor shows the computed moment; diagnostics match."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    state = hass.states.get("sensor.living_room_heating_start")
    assert state is not None
    assert dt_util.parse_datetime(state.state) == EXPECTED_START
    assert state.attributes["required_preheat_hours"] == 12.0
    assert state.attributes["temperature_deficit"] == 6.0
    assert state.attributes["forecast_type"] == "hourly"
    assert state.attributes["beyond_forecast"] is False

    preheat = hass.states.get("sensor.living_room_required_pre_heat_time")
    assert preheat is not None
    assert float(preheat.state) == 12.0


async def test_multiple_rooms_predict_independently(hass, freezer, forecast_calls) -> None:
    """Each room subentry gets its own sensors and prediction."""
    freezer.move_to(NOW)
    hass.states.async_set(
        "climate.bedroom", "off", {"current_temperature": 18.0}
    )
    bedroom = {**ROOM_DATA, CONF_CLIMATE_ENTITY: "climate.bedroom"}
    await setup_entry(hass, [room("Living Room"), room("Bedroom", bedroom)])

    living = hass.states.get("sensor.living_room_heating_start")
    assert dt_util.parse_datetime(living.state) == EXPECTED_START

    # Bedroom deficit 3°C at 0.5°C/h -> 6 h pre-heat.
    bedroom_state = hass.states.get("sensor.bedroom_heating_start")
    assert dt_util.parse_datetime(bedroom_state.state) == ARRIVAL - timedelta(hours=6)

    # The forecast is fetched once for the entry, not once per room.
    assert len(forecast_calls) == 1


async def test_chart_attributes(hass, freezer, forecast_calls) -> None:
    """The start sensor carries the indoor trajectory and the clipped forecast."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    state = hass.states.get("sensor.living_room_heating_start")
    curve = state.attributes["predicted_temperatures"]
    # Flat from now at the current temperature, target reached at arrival.
    assert curve[0] == {"datetime": NOW.isoformat(), "temperature": 15.0}
    assert curve[1] == {"datetime": EXPECTED_START.isoformat(), "temperature": 15.0}
    assert curve[-1] == {"datetime": ARRIVAL.isoformat(), "temperature": 21.0}
    temperatures = [point["temperature"] for point in curve]
    assert temperatures == sorted(temperatures)

    # The room sensor no longer carries the forecast; the entry-level
    # forecast sensor does, unclipped.
    assert "outdoor_forecast" not in state.attributes
    forecast_sensor = hass.states.get("sensor.vacation_heating_outdoor_forecast")
    assert float(forecast_sensor.state) == 0.0
    assert forecast_sensor.attributes["forecast_type"] == "hourly"
    outdoor = forecast_sensor.attributes["forecast"]
    assert outdoor[0] == {"datetime": NOW.isoformat(), "temperature": 0.0}
    assert outdoor[-1]["datetime"] == (NOW + timedelta(hours=119)).isoformat()


async def test_preset_only_action_targets_preset_temperature(
    hass, freezer, forecast_calls
) -> None:
    """With a preset-only action the mapped preset temperature drives the prediction."""
    freezer.move_to(NOW)
    preset_room = {
        **ROOM_DATA,
        CONF_ACTION: "set_preset",
        CONF_PRESET_TEMPERATURES: [
            {"preset": "comfort", "temperature": 18},
            {"preset": "eco", "temperature": 16},
        ],
    }
    await setup_entry(hass, [room("Living Room", preset_room)])

    # Deficit 18 - 15 = 3°C at 0.5°C/h -> 6 h instead of 12 h.
    state = hass.states.get("sensor.living_room_heating_start")
    assert dt_util.parse_datetime(state.state) == ARRIVAL - timedelta(hours=6)
    assert state.attributes["temperature_deficit"] == 3.0


async def test_trigger_fires_configured_action_once(hass, freezer, forecast_calls) -> None:
    """At the computed start the climate services are called exactly once."""
    freezer.move_to(NOW)
    await setup_entry(hass)
    preset_calls = async_mock_service(hass, "climate", "set_preset_mode")
    temp_calls = async_mock_service(hass, "climate", "set_temperature")

    # Just before the computed start: nothing happens.
    freezer.move_to(EXPECTED_START - timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(preset_calls) == 0
    assert len(temp_calls) == 0

    # Past the computed start: both services fire.
    freezer.move_to(EXPECTED_START + timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    # Fire again to flush any re-scheduled trigger from a concurrent refresh.
    freezer.move_to(EXPECTED_START + timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(preset_calls) == 1
    assert preset_calls[0].data == {
        "entity_id": "climate.living_room",
        "preset_mode": "comfort",
    }
    assert len(temp_calls) == 1
    assert temp_calls[0].data == {
        "entity_id": "climate.living_room",
        "temperature": 21.0,
    }

    # Later refreshes must not fire the action again for the same end date.
    freezer.move_to(EXPECTED_START + timedelta(hours=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(preset_calls) == 1
    assert len(temp_calls) == 1


async def test_trigger_guard_survives_reload(hass, freezer, forecast_calls) -> None:
    """After a reload (simulating a restart) the action is not fired again."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)
    preset_calls = async_mock_service(hass, "climate", "set_preset_mode")
    temp_calls = async_mock_service(hass, "climate", "set_temperature")

    freezer.move_to(EXPECTED_START + timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(preset_calls) == 1

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    freezer.move_to(EXPECTED_START + timedelta(minutes=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(preset_calls) == 1
    assert len(temp_calls) == 1


async def test_idle_when_end_date_in_past(hass, freezer, forecast_calls) -> None:
    """A past end date leaves the sensors unknown and schedules nothing."""
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("UTC")
    hass.states.async_set("climate.living_room", "off", {"current_temperature": 15.0})
    hass.states.async_set("weather.home", "sunny")
    hass.states.async_set("input_datetime.vacation_end", "2026-07-01 12:00:00")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vacation Heating",
        data={},
        options=SHARED_OPTIONS,
        subentries_data=[room("Living Room")],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.living_room_heating_start")
    assert state.state == "unknown"


async def test_refreshes_on_end_date_change(hass, freezer, forecast_calls) -> None:
    """Changing the end date entity recomputes the prediction immediately."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    hass.states.async_set("input_datetime.vacation_end", "2026-07-21 12:00:00")
    # The coordinator debounces refresh requests; advance past the cooldown.
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.living_room_heating_start")
    assert dt_util.parse_datetime(state.state) == EXPECTED_START + timedelta(days=1)
