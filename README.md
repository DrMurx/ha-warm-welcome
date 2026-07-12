# Vacation Heating

A Home Assistant custom integration for slow heating systems (e.g. floor
heating). While you are away, your heating is turned down. Based on the
weather forecast and the known heating rate of each room, this integration
predicts **exactly when the heating must be turned back on** so the room is
warm the moment you return from vacation — and turns it on at that moment.

Lowering the heating when you leave is up to you (manually or via your own
automation); this integration handles the predictive re-heat.

## How it works

For each room you configure:

- a **climate entity** — the room's thermostat (provides the current room
  temperature and receives the re-heat command),
- a **weather entity** — provides the outdoor temperature forecast (hourly
  preferred, falls back to twice-daily/daily),
- a **vacation end date entity** — an `input_datetime` (date-only or with
  time), `date`, or `datetime` entity holding when you return,
- an **arrival time** — used when the end date entity carries no time,
- a **target temperature** — what the room should be when you arrive,
- a **heat rate map** — how fast the room heats up (°C/hour) at specific
  outdoor temperatures, e.g. `-10: 0.2`, `0: 0.4`, `10: 0.7`. Rates between
  the mapped points are interpolated linearly and clamped outside the range,
- an **action** — whether to set a preset, a temperature, or both when the
  calculated start time is reached. The preset dropdown offers the presets
  advertised by the selected climate entity (e.g. `comfort`, `eco`,
  `boost`).

Every 30 minutes (and whenever one of the source entities changes) the
integration walks backward from your arrival time through the forecast,
accumulating the degrees the room gains per hour at the forecasted outdoor
temperature, until the gap between the current and the target room
temperature is covered. That point in time is the heating start:

- `sensor.<name>_heating_start` — timestamp of the computed start (with
  diagnostic attributes: required pre-heat hours, temperature deficit,
  forecast type used, whether the prediction had to extrapolate beyond the
  forecast),
- `sensor.<name>_required_preheat` — required pre-heat duration in hours.

When the start moment arrives (and the end date is still in the future),
the configured action is executed once per vacation. The "already
triggered" flag survives Home Assistant restarts. If Home Assistant was
down at the computed moment, the action fires immediately after startup.

If the end date entity is unset or in the past, the integration idles and
the sensors show `unknown`.

## Installation

### HACS (recommended)

1. In HACS, add this repository as a **custom repository** of type
   *Integration*.
2. Install **Vacation Heating** and restart Home Assistant.

### Manual

Copy `custom_components/vacation_heating` into the `custom_components`
folder of your Home Assistant configuration directory and restart.

## Configuration

Everything is configured in the UI: **Settings → Devices & services →
Add integration → Vacation Heating**. Create one entry per room. Setup has
two steps: first pick the entities, then the schedule, heat rates, and the
action — the preset choices in the second step come from the climate
entity you picked in the first.

Heat rate entries are typed as `outdoor temperature: rate` chips (e.g.
`-10: 0.2` means: at -10 °C outside, the room gains 0.2 °C per hour). They
are validated and sorted automatically.

All settings can be changed later via the entry's **Configure** (options)
or **Reconfigure** menu — including the room name.

### Determining your heat rates

Turn the heating on from a cooled-down state on days with different outdoor
temperatures and note how many degrees the room gains per hour. One or two
points are enough to start; add more points for better predictions.

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
