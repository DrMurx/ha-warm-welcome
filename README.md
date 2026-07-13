# Vacation Heating

A Home Assistant custom integration for slow heating systems (e.g. floor
heating). While you are away, your heating is turned down. Based on the
weather forecast and the known heating rate of each room, this integration
predicts **exactly when the heating must be turned back on** so the room is
warm the moment you return from vacation — and turns it on at that moment.

Lowering the heating when you leave is up to you (manually or via your own
automation); this integration handles the predictive re-heat.

## How it works

The integration is set up once with the entities shared by all rooms:

- a **weather entity** — provides the outdoor temperature forecast (hourly
  preferred, falls back to twice-daily/daily),
- a **vacation end entity** — an `input_datetime` (with time enabled) or
  `datetime` entity holding the date and time you return.

Then you add each **room** to it, configuring:

- a **climate entity** — the room's thermostat (provides the current room
  temperature and receives the re-heat command),
- a **target temperature** — what the room should be when you arrive,
- a **heat rate map** — measurements of how fast the room heats up at
  specific outdoor temperatures. Each point records the outdoor
  temperature, how many degrees the room gained, and over how many hours —
  e.g. "at -10° outside the room gained 1° in 5 hours". The gain may be
  negative if your heating cannot keep up at very low outdoor
  temperatures; the prediction then starts correspondingly earlier so
  warmer hours compensate. Rates between the mapped points are
  interpolated linearly and clamped outside the range,
- an **action** — whether to set a preset, a temperature, or both when the
  calculated start time is reached. The preset dropdown offers the presets
  advertised by the selected climate entity (e.g. `comfort`, `eco`,
  `boost`),
- optional **preset temperatures** — the temperature each preset heats to,
  e.g. `comfort: 21`, `eco: 17`. Presets switch the thermostat to a setpoint
  configured inside the climate device, which this integration cannot read;
  with a preset-only action the prediction targets the mapped temperature
  of the selected preset (falling back to the target temperature if the
  preset is not mapped).

Every 30 minutes (and whenever one of the source entities changes) the
integration walks backward per room from your arrival time through the forecast,
accumulating the degrees the room gains per hour at the forecasted outdoor
temperature, until the gap between the current and the target room
temperature is covered. That point in time is the heating start:

- `sensor.<name>_heating_start` — timestamp of the computed start (with
  diagnostic attributes: required pre-heat hours, temperature deficit,
  forecast type used, whether the prediction had to extrapolate beyond the
  forecast, plus the chart series described below),
- `sensor.<name>_required_preheat` — required pre-heat duration in hours.

When the start moment arrives (and the end date is still in the future),
the configured action is executed once per vacation. The "already
triggered" flag survives Home Assistant restarts. If Home Assistant was
down at the computed moment, the action fires immediately after startup.

If the end date entity is unset or in the past, the integration idles and
the sensors show `unknown`.

## Installation

Requires Home Assistant 2026.1 or newer.

### HACS (recommended)

1. In HACS, add this repository as a **custom repository** of type
   *Integration*.
2. Install **Vacation Heating** and restart Home Assistant.

### Manual

Copy `custom_components/vacation_heating` into the `custom_components`
folder of your Home Assistant configuration directory and restart.

## Configuration

Everything is configured in the UI: **Settings → Devices & services →
Add integration → Vacation Heating**. The integration is added once,
asking for the shared weather and vacation end entities. Then add each
room via **Add room** on the integration's page. Adding a room has two
steps: first the name and climate entity, then the heat rates and the
action — the preset choices in the second step come from the climate
entity you picked in the first.

Heat rate points and preset temperatures are entered as structured list
entries with one small form per point. All temperature fields follow your
Home Assistant unit system (°C or °F); if you ever switch the unit
system, re-enter the configured temperatures in the new unit.

Everything can be changed later: the shared entities via the entry's
**Configure** menu, each room (including its name) via the room's
**Reconfigure** menu.

## Charting the prediction

The `heating_start` sensor exposes two attributes made for charting:

- `predicted_temperatures` — the predicted room temperature as
  `{datetime, temperature}` points: flat at the current temperature from
  now until the heating start, then rising to the target at arrival (with
  a point at every heat-rate change),
- `outdoor_forecast` — the outdoor forecast used for the prediction,
  clipped to the arrival time.

Both attributes are excluded from the recorder (no database growth); they
always reflect the latest prediction, which is recomputed every 30 minutes
and immediately after any source entity or option changes.

With the [ApexCharts card](https://github.com/RomRider/apexcharts-card)
(available via HACS) you can plot the timeline of several rooms in one
chart — the point where a room's line starts rising is its heating start:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Vacation re-heat
graph_span: 8d
span:
  start: hour
series:
  - entity: sensor.living_room_heating_start
    name: Living room
    data_generator: |
      return (entity.attributes.predicted_temperatures || [])
        .map((p) => [new Date(p.datetime), p.temperature]);
  - entity: sensor.bedroom_heating_start
    name: Bedroom
    data_generator: |
      return (entity.attributes.predicted_temperatures || [])
        .map((p) => [new Date(p.datetime), p.temperature]);
  - entity: sensor.living_room_heating_start
    name: Outside
    type: area
    opacity: 0.2
    data_generator: |
      return (entity.attributes.outdoor_forecast || [])
        .map((p) => [new Date(p.datetime), p.temperature]);
```

Adjust `graph_span` to cover your longest expected pre-heat plus the time
until arrival. While no vacation end is set, the sensors are `unknown` and
the series are empty.

### Determining your heat rates

Turn the heating on from a cooled-down state on days with different outdoor
temperatures and note how many degrees the room gained over how many hours —
that measurement is entered directly, no conversion to an hourly rate
needed. One or two points are enough to start; add more points for better
predictions. If the room *loses* temperature despite full heating on very
cold days, enter that as a negative gain.

## Development

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt
ruff check .
pytest tests/ -v
```

## Releasing

Publish a GitHub release with a tag like `v0.1.1`. The release workflow
stamps the version into the manifest and uploads `vacation_heating.zip`,
which HACS installs.
