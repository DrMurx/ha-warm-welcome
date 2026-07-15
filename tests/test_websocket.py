"""Tests for the websocket API and card registration."""

from datetime import timedelta

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    CLIENT_ID,
    async_fire_time_changed,
)
from test_init import ARRIVAL, EXPECTED_START, NOW, setup_entry


async def _frozen_time_token(hass: HomeAssistant, hass_admin_user) -> str:
    """An access token issued at the frozen time.

    The hass_ws_client fixture's default token is minted at real time and
    is already expired once the test freezes a date days ahead.
    """
    refresh_token = await hass.auth.async_create_refresh_token(
        hass_admin_user, CLIENT_ID
    )
    return hass.auth.async_create_access_token(refresh_token)


async def test_subscribe_receives_data_and_updates(
    hass: HomeAssistant, freezer, forecast_calls, hass_ws_client, hass_admin_user
) -> None:
    """The card subscription gets an initial payload and live updates."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    client = await hass_ws_client(hass, await _frozen_time_token(hass, hass_admin_user))
    await client.send_json({"id": 1, "type": "vacation_heating/subscribe"})
    result = await client.receive_json()
    assert result["success"]

    message = await client.receive_json()
    payload = message["event"]
    assert payload["arrival"] == ARRIVAL.isoformat()
    assert payload["unit"] == "°C"
    assert payload["forecast"][0]["temperature"] == 0.0
    (room,) = payload["rooms"]
    assert room["name"] == "Living Room"
    assert room["start"] == EXPECTED_START.isoformat()
    assert room["beyond_forecast"] is False
    assert room["curve"][0] == {
        "datetime": EXPECTED_START.isoformat(),
        "temperature": 15.0,
    }
    assert room["curve"][-1] == {
        "datetime": ARRIVAL.isoformat(),
        "temperature": 21.0,
    }

    # A changed end date pushes an updated prediction.
    hass.states.async_set("input_datetime.vacation_end", "2026-07-21 12:00:00")
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    message = await client.receive_json()
    payload = message["event"]
    assert payload["rooms"][0]["start"] == (
        EXPECTED_START + timedelta(days=1)
    ).isoformat()


async def test_subscription_survives_config_entity_reload(
    hass: HomeAssistant, freezer, forecast_calls, hass_ws_client, hass_admin_user
) -> None:
    """Changing a config entity reloads the entry; the card gets fresh data.

    Regression test: the refresh dispatched at the end of the reload used
    to fire before the entry state was LOADED, pushing the empty payload
    and locking the card into "no upcoming re-heat".
    """
    freezer.move_to(NOW)
    await setup_entry(hass)

    client = await hass_ws_client(hass, await _frozen_time_token(hass, hass_admin_user))
    await client.send_json({"id": 1, "type": "vacation_heating/subscribe"})
    assert (await client.receive_json())["success"]
    await client.receive_json()  # initial payload

    await hass.services.async_call(
        "number",
        "set_value",
        {
            "entity_id": "number.living_room_vacation_heating_target_temperature",
            "value": 22.0,
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    message = await client.receive_json()
    payload = message["event"]
    (room,) = payload["rooms"]
    assert room["name"] == "Living Room"
    # Deficit is now 7°C at 0.5°C/h -> 14 h pre-heat.
    assert room["start"] == (ARRIVAL - timedelta(hours=14)).isoformat()
    assert room["curve"][-1]["temperature"] == 22.0


async def test_subscribe_without_a_loaded_entry(
    hass: HomeAssistant, hass_ws_client
) -> None:
    """Without a set-up entry the subscription reports an empty state."""
    assert await async_setup_component(hass, "vacation_heating", {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "vacation_heating/subscribe"})
    result = await client.receive_json()
    assert result["success"]
    message = await client.receive_json()
    assert message["event"] == {
        "arrival": None,
        "unit": "°C",
        "forecast": [],
        "rooms": [],
    }


async def test_card_module_registered(
    hass: HomeAssistant, freezer, forecast_calls
) -> None:
    """Setting up the integration serves and loads the bundled card."""
    freezer.move_to(NOW)
    await setup_entry(hass)

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any("vacation-heating-card.js" in url for url in urls)
