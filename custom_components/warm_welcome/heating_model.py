"""Pure prediction math for the Warm Welcome integration.

This module has no Home Assistant imports so it can be unit tested in
isolation. All temperatures are in Home Assistant's configured unit
system (°C or °F); heat rates are degrees per hour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

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
    """Outcome of a pre-heat prediction.

    ``curve`` is the predicted indoor temperature trajectory as
    (time, temperature) points from the heating start to the arrival,
    with a point at every heat-rate change.
    """

    start: datetime
    preheat_hours: float
    deficit: float
    beyond_forecast: bool
    curve: list[tuple[datetime, float]]


def parse_heat_rates(entries: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Parse measured heat rate points into sorted (outdoor_temp, rate) pairs.

    Each entry is a measurement: at ``outdoor_temp`` outside, the room
    gained ``gain`` degrees in ``hours`` hours; the rate is degrees per
    hour. Gains may be negative or zero (a heating that cannot keep up),
    but every duration must be positive and at least one point must have
    a positive rate. Raises ValueError on malformed entries, duplicate
    outdoor temperatures, or an empty list.
    """
    pairs: list[tuple[float, float]] = []
    for entry in entries:
        try:
            temp = float(entry["outdoor_temp"])
            gain = float(entry["gain"])
            hours = float(entry["hours"])
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError(f"invalid heat rate entry {entry!r}") from err
        if hours <= 0:
            raise ValueError(f"duration must be positive in heat rate entry {entry!r}")
        pairs.append((temp, gain / hours))
    if not pairs:
        raise ValueError("at least one heat rate entry is required")
    pairs.sort(key=lambda pair: pair[0])
    temps = [temp for temp, _ in pairs]
    if len(set(temps)) != len(temps):
        raise ValueError("duplicate outdoor temperature in heat rate entries")
    if all(rate <= 0 for _, rate in pairs):
        raise ValueError("at least one heat rate must be positive")
    return pairs


def parse_preset_temperatures(entries: list[dict[str, Any]]) -> dict[str, float]:
    """Parse preset temperature points; an empty list is allowed.

    Each entry maps a ``preset`` name to the ``temperature`` it heats to.
    Raises ValueError on malformed entries or duplicate presets.
    """
    presets: dict[str, float] = {}
    for entry in entries:
        try:
            preset = str(entry["preset"]).strip()
            temperature = float(entry["temperature"])
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError(f"invalid preset temperature entry {entry!r}") from err
        if not preset:
            raise ValueError(f"missing preset name in entry {entry!r}")
        if preset in presets:
            raise ValueError(f"duplicate preset in entry {entry!r}")
        presets[preset] = temperature
    return presets


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


def _temperature_after(
    points: list[ForecastPoint], moment: datetime
) -> tuple[float, datetime]:
    """Outdoor temperature for the interval starting at ``moment``.

    Returns (temperature, interval_end). ``points`` must be sorted
    ascending by time and non-empty.
    """
    if moment < points[0].time:
        # Before forecast coverage: extrapolate with the earliest value.
        return points[0].temperature, min(points[0].time, moment + FALLBACK_STEP)
    for point, successor in pairwise(points):
        if point.time <= moment < successor.time:
            return point.temperature, successor.time
    # At or after the last point: extrapolate with the latest value.
    return points[-1].temperature, moment + FALLBACK_STEP


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
    warmup: timedelta = timedelta(0),
) -> PredictionResult:
    """Compute when heating must start to reach target_temp by ``arrival``.

    Walks backward from the arrival time through the forecast, accumulating
    degrees heated per interval at the interpolated heat rate, until the
    temperature deficit is covered. Negative rates (a heating that cannot
    keep up at that outdoor temperature) enlarge the deficit, requiring
    even earlier positive intervals to compensate. If the required lead
    time extends past forecast coverage (or ``max_lookback``), the result
    is flagged ``beyond_forecast``.

    ``warmup`` is the time the heating spends warming the floor's thermal
    mass before the room gains any heat; it shifts the start that much
    earlier and prepends a flat segment to the curve.
    """
    deficit = target_temp - current_temp
    if deficit <= 0 or not forecast:
        temperature = target_temp if deficit > 0 else current_temp
        return PredictionResult(
            arrival,
            0.0,
            max(deficit, 0.0),
            not forecast and deficit > 0,
            [(arrival, temperature)],
        )

    points = sorted(forecast, key=lambda p: p.time)
    moment = arrival
    remaining = deficit
    beyond = False
    # Built backward from the arrival; the room is current_temp + remaining
    # at each interval boundary.
    curve = [(arrival, target_temp)]

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
        curve.append((moment, current_temp + remaining))

    if warmup > timedelta(0):
        moment -= warmup
        curve.append((moment, current_temp + remaining))

    curve.reverse()
    preheat_hours = (arrival - moment).total_seconds() / 3600
    return PredictionResult(moment, preheat_hours, deficit, beyond, curve)


def compute_reach(
    start: datetime,
    current_temp: float,
    target_temp: float,
    forecast: list[ForecastPoint],
    rates: list[tuple[float, float]],
    max_lookahead: timedelta = DEFAULT_MAX_LOOKBACK,
    warmup: timedelta = timedelta(0),
) -> datetime | None:
    """Compute when the room reaches target_temp if heating runs from ``start``.

    The forward counterpart of compute_start: walks forward from ``start``
    through the forecast, accumulating degrees heated per interval at the
    interpolated heat rate, until the temperature deficit is covered.
    The room only starts gaining heat once the floor's thermal mass is
    warm, ``warmup`` after the start. Returns None if the target is not
    reached within ``max_lookahead`` (e.g. the heating cannot keep up at
    the forecasted temperatures) or when there is no forecast to walk
    through.
    """
    remaining = target_temp - current_temp
    if remaining <= 0:
        return start
    if not forecast:
        return None

    points = sorted(forecast, key=lambda p: p.time)
    moment = start + warmup
    while moment - start < max_lookahead:
        temperature, interval_end = _temperature_after(points, moment)
        rate = rate_at(rates, temperature)
        interval_hours = (interval_end - moment).total_seconds() / 3600
        gain = rate * interval_hours
        if gain >= remaining:
            return moment + timedelta(hours=remaining / rate)
        remaining -= gain
        moment = interval_end
    return None
