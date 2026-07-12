"""Pure prediction math for the Vacation Heating integration.

This module has no Home Assistant imports so it can be unit tested in
isolation. All temperatures are in the unit the user configured their
system with (typically °C); heat rates are degrees per hour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

DEFAULT_MAX_LOOKBACK = timedelta(days=14)
# Assumed coverage of a single forecast point when the interval cannot be
# derived from neighbouring points.
FALLBACK_STEP = timedelta(hours=1)


@dataclass(frozen=True)
class ForecastPoint:
    """A single outdoor temperature forecast value."""

    time: datetime
    temperature: float


@dataclass(frozen=True)
class PredictionResult:
    """Outcome of a pre-heat prediction."""

    start: datetime
    preheat_hours: float
    deficit: float
    beyond_forecast: bool


def parse_heat_rate(entry: str) -> tuple[float, float]:
    """Parse a single 'outdoor_temp: rate' pair.

    Raises ValueError if the entry is malformed or the rate is not positive.
    """
    temp_str, sep, rate_str = entry.partition(":")
    if not sep:
        raise ValueError(f"missing ':' in heat rate entry {entry!r}")
    try:
        temp = float(temp_str.strip().replace(",", "."))
        rate = float(rate_str.strip().replace(",", "."))
    except ValueError as err:
        raise ValueError(f"invalid number in heat rate entry {entry!r}") from err
    if rate <= 0:
        raise ValueError(f"heat rate must be positive in entry {entry!r}")
    return temp, rate


def parse_heat_rates(entries: list[str]) -> list[tuple[float, float]]:
    """Parse and sort a list of 'outdoor_temp: rate' pairs by temperature.

    Raises ValueError on malformed entries, duplicate temperatures, or an
    empty list.
    """
    pairs = [parse_heat_rate(entry) for entry in entries]
    if not pairs:
        raise ValueError("at least one heat rate entry is required")
    pairs.sort(key=lambda pair: pair[0])
    temps = [temp for temp, _ in pairs]
    if len(set(temps)) != len(temps):
        raise ValueError("duplicate outdoor temperature in heat rate entries")
    return pairs


def format_heat_rates(pairs: list[tuple[float, float]]) -> list[str]:
    """Format sorted pairs back into canonical 'temp: rate' strings."""
    return [f"{temp:g}: {rate:g}" for temp, rate in pairs]


def rate_at(rates: list[tuple[float, float]], outdoor_temp: float) -> float:
    """Heat rate (degrees/hour) at an outdoor temperature.

    Linearly interpolates between the two nearest mapped points and clamps
    to the boundary rates outside the mapped range. ``rates`` must be
    sorted by temperature (as returned by parse_heat_rates).
    """
    if outdoor_temp <= rates[0][0]:
        return rates[0][1]
    if outdoor_temp >= rates[-1][0]:
        return rates[-1][1]
    for (t_low, r_low), (t_high, r_high) in pairwise(rates):
        if t_low <= outdoor_temp <= t_high:
            fraction = (outdoor_temp - t_low) / (t_high - t_low)
            return r_low + fraction * (r_high - r_low)
    raise AssertionError("unreachable: rates not sorted?")


def _temperature_before(
    points: list[ForecastPoint], moment: datetime
) -> tuple[float, datetime, bool]:
    """Outdoor temperature for the interval ending at ``moment``.

    Returns (temperature, interval_start, beyond_forecast). ``points`` must
    be sorted ascending by time and non-empty.
    """
    if moment <= points[0].time:
        # Before forecast coverage: extrapolate with the earliest value.
        return points[0].temperature, moment - FALLBACK_STEP, True

    last_covered = points[-1].time + _typical_step(points)
    if moment > last_covered:
        # After forecast coverage: extrapolate with the latest value.
        return points[-1].temperature, max(last_covered, moment - FALLBACK_STEP), True

    # Find the latest point strictly before ``moment``; it defines the
    # temperature of the interval [point.time, moment).
    for point in reversed(points):
        if point.time < moment:
            return point.temperature, point.time, False
    raise AssertionError("unreachable: covered above")


def _typical_step(points: list[ForecastPoint]) -> timedelta:
    if len(points) < 2:
        return FALLBACK_STEP
    return points[1].time - points[0].time


def compute_start(
    arrival: datetime,
    current_temp: float,
    target_temp: float,
    forecast: list[ForecastPoint],
    rates: list[tuple[float, float]],
    max_lookback: timedelta = DEFAULT_MAX_LOOKBACK,
) -> PredictionResult:
    """Compute when heating must start to reach target_temp by ``arrival``.

    Walks backward from the arrival time through the forecast, accumulating
    degrees heated per interval at the interpolated heat rate, until the
    temperature deficit is covered. If the required lead time extends past
    forecast coverage (or ``max_lookback``), the result is flagged
    ``beyond_forecast``.
    """
    deficit = target_temp - current_temp
    if deficit <= 0 or not forecast:
        return PredictionResult(arrival, 0.0, max(deficit, 0.0), not forecast and deficit > 0)

    points = sorted(forecast, key=lambda p: p.time)
    moment = arrival
    remaining = deficit
    beyond = False

    while remaining > 0:
        if arrival - moment >= max_lookback:
            beyond = True
            break
        temperature, interval_start, interval_beyond = _temperature_before(points, moment)
        beyond = beyond or interval_beyond
        rate = rate_at(rates, temperature)
        interval_hours = (moment - interval_start).total_seconds() / 3600
        gain = rate * interval_hours
        if gain >= remaining:
            moment -= timedelta(hours=remaining / rate)
            remaining = 0.0
        else:
            remaining -= gain
            moment = interval_start

    preheat_hours = (arrival - moment).total_seconds() / 3600
    return PredictionResult(moment, preheat_hours, deficit, beyond)
