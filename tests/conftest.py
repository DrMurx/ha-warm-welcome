"""Common fixtures for the Warm Welcome tests."""

from datetime import timedelta

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture(autouse=True)
def no_settle_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero the preset-to-temperature settle delay.

    Under the frozen test clock a real asyncio.sleep never wakes up;
    sleep(0) yields without arming a timer.
    """
    monkeypatch.setattr(
        "custom_components.warm_welcome.coordinator.TRIGGER_SETTLE_DELAY", 0
    )


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
