"""Tests for the pure prediction math."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest

from custom_components.warm_welcome.heating_model import (
    ForecastPoint,
    compute_reach,
    compute_start,
    parse_heat_rates,
    parse_preset_temperatures,
    rate_at,
)

ARRIVAL = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def hourly_forecast(start: datetime, hours: int, temperature: float) -> list[ForecastPoint]:
    return [
        ForecastPoint(start + timedelta(hours=i), temperature) for i in range(hours)
    ]


def hr(outdoor_temp, gain, hours) -> dict:
    return {"outdoor_temp": outdoor_temp, "gain": gain, "hours": hours}


class TestParseHeatRates:
    def test_parses_and_sorts(self):
        rates = parse_heat_rates([hr(10, 3.5, 5), hr(-10, 1, 5), hr(0, 2, 5)])
        assert rates == [(-10.0, 0.2), (0.0, 0.4), (10.0, 0.7)]

    def test_accepts_negative_and_zero_gains(self):
        rates = parse_heat_rates([hr(-20, -1, 4), hr(-10, 0, 4), hr(0, 2, 4)])
        assert rates == [(-20.0, -0.25), (-10.0, 0.0), (0.0, 0.5)]

    def test_rejects_missing_field(self):
        with pytest.raises(ValueError, match="invalid heat rate"):
            parse_heat_rates([{"outdoor_temp": 0, "gain": 1}])

    def test_rejects_non_numeric(self):
        with pytest.raises(ValueError, match="invalid heat rate"):
            parse_heat_rates([hr("cold", "fast", 1)])

    def test_rejects_non_positive_duration(self):
        with pytest.raises(ValueError, match="duration"):
            parse_heat_rates([hr(0, 1, 0)])

    def test_rejects_all_non_positive_rates(self):
        with pytest.raises(ValueError, match="positive"):
            parse_heat_rates([hr(-10, -1, 2), hr(0, 0, 2)])

    def test_rejects_duplicates(self):
        with pytest.raises(ValueError, match="duplicate"):
            parse_heat_rates([hr(0, 1, 2), hr(0, 2, 2)])

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="at least one"):
            parse_heat_rates([])


def pt(preset, temperature) -> dict:
    return {"preset": preset, "temperature": temperature}


class TestParsePresetTemperatures:
    def test_parses(self):
        presets = parse_preset_temperatures([pt("comfort", 21), pt(" eco ", 17.5)])
        assert presets == {"comfort": 21.0, "eco": 17.5}

    def test_empty_list_is_allowed(self):
        assert parse_preset_temperatures([]) == {}

    def test_rejects_missing_field(self):
        with pytest.raises(ValueError, match="invalid preset"):
            parse_preset_temperatures([{"preset": "comfort"}])

    def test_rejects_empty_preset(self):
        with pytest.raises(ValueError, match="missing preset name"):
            parse_preset_temperatures([pt("  ", 21)])

    def test_rejects_non_numeric_temperature(self):
        with pytest.raises(ValueError, match="invalid preset"):
            parse_preset_temperatures([pt("comfort", "warm")])

    def test_rejects_duplicates(self):
        with pytest.raises(ValueError, match="duplicate"):
            parse_preset_temperatures([pt("eco", 17), pt("eco", 18)])


class TestRateAt:
    RATES: ClassVar = [(-10.0, 0.2), (0.0, 0.4), (10.0, 0.8)]

    def test_exact_points(self):
        assert rate_at(self.RATES, -10) == 0.2
        assert rate_at(self.RATES, 0) == 0.4
        assert rate_at(self.RATES, 10) == 0.8

    def test_linear_interpolation(self):
        assert rate_at(self.RATES, -5) == pytest.approx(0.3)
        assert rate_at(self.RATES, 5) == pytest.approx(0.6)

    def test_clamps_outside_range(self):
        assert rate_at(self.RATES, -30) == 0.2
        assert rate_at(self.RATES, 25) == 0.8


class TestComputeStart:
    RATES: ClassVar = [(0.0, 0.4)]

    def test_no_deficit_starts_at_arrival(self):
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=48), 120, 0.0)
        result = compute_start(ARRIVAL, 21.0, 21.0, forecast, self.RATES)
        assert result.start == ARRIVAL
        assert result.preheat_hours == 0.0
        assert not result.beyond_forecast
        assert result.curve == [(ARRIVAL, 21.0)]

    def test_constant_temperature(self):
        # 2°C deficit at 0.4°C/h -> 5 hours of pre-heating.
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=48), 120, 0.0)
        result = compute_start(ARRIVAL, 19.0, 21.0, forecast, self.RATES)
        assert result.start == ARRIVAL - timedelta(hours=5)
        assert result.preheat_hours == pytest.approx(5.0)
        assert result.deficit == pytest.approx(2.0)
        assert not result.beyond_forecast

    def test_curve_rises_from_start_to_arrival(self):
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=48), 120, 0.0)
        result = compute_start(ARRIVAL, 19.0, 21.0, forecast, self.RATES)
        assert result.curve[0] == (result.start, 19.0)
        assert result.curve[-1] == (ARRIVAL, 21.0)
        times = [when for when, _ in result.curve]
        temps = [temperature for _, temperature in result.curve]
        assert times == sorted(times)
        assert temps == sorted(temps)
        # One point per hourly forecast boundary within the 5-hour pre-heat.
        assert ARRIVAL - timedelta(hours=2) in times
        assert temps[times.index(ARRIVAL - timedelta(hours=2))] == pytest.approx(20.2)

    def test_varying_temperature(self):
        # Rates: 0.2 at -10°C, 0.4 at 0°C. Forecast: -10°C for the 2 hours
        # before arrival, 0°C earlier. Deficit 1°C: last 2 hours heat
        # 2*0.2=0.4°C, remaining 0.6°C at 0.4°C/h takes 1.5h -> 3.5h total.
        rates = [(-10.0, 0.2), (0.0, 0.4)]
        start = ARRIVAL - timedelta(hours=48)
        forecast = [
            ForecastPoint(start + timedelta(hours=i), -10.0 if i >= 46 else 0.0)
            for i in range(49)
        ]
        result = compute_start(ARRIVAL, 20.0, 21.0, forecast, rates)
        assert result.start == ARRIVAL - timedelta(hours=3, minutes=30)
        assert result.preheat_hours == pytest.approx(3.5)

    def test_negative_rate_extends_preheat(self):
        # The heating loses 0.25°C/h during the two -10°C hours before
        # arrival; earlier heating at 0°C must compensate. Deficit 1°C:
        # cold hours add 0.5°C -> 1.5°C at 0.5°C/h -> 3 h -> 5 h total.
        rates = [(-10.0, -0.25), (0.0, 0.5)]
        start = ARRIVAL - timedelta(hours=48)
        forecast = [
            ForecastPoint(start + timedelta(hours=i), -10.0 if i >= 46 else 0.0)
            for i in range(49)
        ]
        result = compute_start(ARRIVAL, 20.0, 21.0, forecast, rates)
        assert result.start == ARRIVAL - timedelta(hours=5)
        assert result.preheat_hours == pytest.approx(5.0)
        assert not result.beyond_forecast
        # The curve dips during the cold hours before recovering to target.
        temps = [temperature for _, temperature in result.curve]
        assert max(temps) == pytest.approx(21.5)
        assert temps[-1] == 21.0

    def test_uncoverable_deficit_hits_lookback(self):
        # 10°C outside everywhere maps to a negative rate, so the deficit
        # is never covered and the lookback cap applies.
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=48), 120, 10.0)
        result = compute_start(
            ARRIVAL,
            20.0,
            21.0,
            forecast,
            [(0.0, 0.5), (10.0, -0.1)],
            max_lookback=timedelta(hours=10),
        )
        assert result.start == ARRIVAL - timedelta(hours=10)
        assert result.beyond_forecast

    def test_sub_hour_precision(self):
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=48), 120, 0.0)
        # 0.1°C deficit at 0.4°C/h -> 15 minutes.
        result = compute_start(ARRIVAL, 20.9, 21.0, forecast, self.RATES)
        assert result.start == ARRIVAL - timedelta(minutes=15)

    def test_beyond_forecast_extrapolates_earliest_value(self):
        # Only 2 hours of forecast before arrival, but 5 hours needed.
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=2), 3, 0.0)
        result = compute_start(ARRIVAL, 19.0, 21.0, forecast, self.RATES)
        assert result.start == ARRIVAL - timedelta(hours=5)
        assert result.beyond_forecast

    def test_arrival_after_forecast_extrapolates_latest_value(self):
        # Forecast ends 10 hours before arrival.
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=20), 10, 0.0)
        result = compute_start(ARRIVAL, 19.0, 21.0, forecast, self.RATES)
        assert result.start == ARRIVAL - timedelta(hours=5)
        assert result.beyond_forecast

    def test_max_lookback_caps_start(self):
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=48), 120, 0.0)
        result = compute_start(
            ARRIVAL, 0.0, 21.0, forecast, self.RATES, max_lookback=timedelta(hours=10)
        )
        assert result.start == ARRIVAL - timedelta(hours=10)
        assert result.beyond_forecast

    def test_empty_forecast_with_deficit(self):
        result = compute_start(ARRIVAL, 19.0, 21.0, [], self.RATES)
        assert result.start == ARRIVAL
        assert result.beyond_forecast


class TestComputeReach:
    RATES: ClassVar = [(0.0, 0.4)]
    START = ARRIVAL - timedelta(hours=12)

    def test_no_deficit_reaches_immediately(self):
        forecast = hourly_forecast(self.START, 120, 0.0)
        assert compute_reach(self.START, 21.0, 21.0, forecast, self.RATES) == self.START

    def test_constant_temperature(self):
        # 2°C deficit at 0.4°C/h -> reached after 5 hours.
        forecast = hourly_forecast(self.START, 120, 0.0)
        reached = compute_reach(self.START, 19.0, 21.0, forecast, self.RATES)
        assert reached == self.START + timedelta(hours=5)

    def test_mirrors_compute_start(self):
        # Walking forward from the computed start must land on the arrival.
        forecast = hourly_forecast(ARRIVAL - timedelta(hours=48), 120, 0.0)
        result = compute_start(ARRIVAL, 19.0, 21.0, forecast, self.RATES)
        reached = compute_reach(result.start, 19.0, 21.0, forecast, self.RATES)
        assert reached == ARRIVAL

    def test_varying_temperature(self):
        # Rates: 0.2 at -10°C, 0.4 at 0°C. Forecast: -10°C for the first
        # 2 hours, 0°C afterwards. Deficit 1°C: the cold hours heat
        # 2*0.2=0.4°C, remaining 0.6°C at 0.4°C/h takes 1.5h -> 3.5h total.
        rates = [(-10.0, 0.2), (0.0, 0.4)]
        forecast = [
            ForecastPoint(self.START + timedelta(hours=i), -10.0 if i < 2 else 0.0)
            for i in range(49)
        ]
        reached = compute_reach(self.START, 20.0, 21.0, forecast, rates)
        assert reached == self.START + timedelta(hours=3, minutes=30)

    def test_negative_rate_delays_reach(self):
        # The heating loses 0.25°C/h during the first two -10°C hours;
        # deficit 1°C grows to 1.5°C, then 0.5°C/h -> 3h -> 5h total.
        rates = [(-10.0, -0.25), (0.0, 0.5)]
        forecast = [
            ForecastPoint(self.START + timedelta(hours=i), -10.0 if i < 2 else 0.0)
            for i in range(49)
        ]
        reached = compute_reach(self.START, 20.0, 21.0, forecast, rates)
        assert reached == self.START + timedelta(hours=5)

    def test_extrapolates_past_forecast_end(self):
        # Only 2 hours of forecast; the remaining deficit is covered by
        # extrapolating the latest value. 2°C at 0.4°C/h -> 5 hours.
        forecast = hourly_forecast(self.START, 2, 0.0)
        reached = compute_reach(self.START, 19.0, 21.0, forecast, self.RATES)
        assert reached == self.START + timedelta(hours=5)

    def test_unreachable_within_lookahead_returns_none(self):
        # 10°C outside everywhere maps to a negative rate: never reached.
        forecast = hourly_forecast(self.START, 120, 10.0)
        reached = compute_reach(
            self.START,
            20.0,
            21.0,
            forecast,
            [(0.0, 0.5), (10.0, -0.1)],
            max_lookahead=timedelta(hours=10),
        )
        assert reached is None

    def test_empty_forecast_returns_none(self):
        assert compute_reach(self.START, 19.0, 21.0, [], self.RATES) is None
