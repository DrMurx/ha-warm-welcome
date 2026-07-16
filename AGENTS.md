# AGENTS.md

Guidance for AI development agents working on this repository.

## What this project is

**Warm Welcome** is a Home Assistant custom integration (HACS-installable)
for slow heating systems such as floor heating. While the user is away, the
heating is turned down; based on the outdoor temperature forecast and a
per-room heat rate map, the integration predicts when the heating must be
turned back on so each room is warm exactly at the vacation end — and triggers
the configured climate action (preset and/or temperature) at that moment.
Turning the heating *down* at departure is deliberately out of scope; only the
predictive re-heat is handled.

The prediction walks backward per room from the arrival time through the
forecast, accumulating degrees gained per hour (interpolated linearly between
the mapped heat-rate points), until the gap between current and target room
temperature is covered. It recomputes every 30 minutes and on any source
entity change. See `README.md` for the full user-facing behavior.

## Layout

- `custom_components/warm_welcome/` — the integration (Python 3.13+,
  Home Assistant 2026.3+). Key modules:
  - `heating_model.py` — pure prediction logic (backward walk, rate
    interpolation); no HA dependencies, easiest to unit-test.
  - `coordinator.py` — recomputation scheduling, source-entity listeners,
    action triggering ("already triggered" flag survives restarts).
  - `config_flow.py` — UI setup: one entry with shared weather + vacation-end
    entities; rooms added as subentries (name/climate first, then heat rates
    and action).
  - `sensor.py` — per-room `heating_start` / `required_preheat` sensors and
    the shared `outdoor_forecast` sensor; chartable point lists live in
    attributes excluded from the recorder.
  - `number.py`, `select.py` — per-room config entities that write back into
    the room's options.
  - `websocket.py` — live data subscription for the bundled card.
  - `frontend/warm-welcome-card.js` — the bundled Lovelace card,
    registered automatically as a static resource.
  - `translations/` — `en`, `de`, `nl`, `fr`, `es`, `pt`; keep all six in
    sync when changing config-flow or entity strings.
- `tests/` — pytest suite built on `pytest-homeassistant-custom-component`.
- The repo is not an installable Python package; it ships via HACS from
  `custom_components/`. `pyproject.toml` only manages the dev environment.

## Development

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync                  # set up the dev environment
uv run ruff check .      # lint (config in pyproject.toml)
uv run pytest tests/ -v  # run the test suite
```

## Conventions

- **Version bump on every component change**: whenever anything under
  `custom_components/warm_welcome/` changes — or a dependency changes
  (manifest `requirements`, `pyproject.toml`/`uv.lock`) — bump the patch
  level in `pyproject.toml`, `custom_components/warm_welcome/manifest.json`,
  and `CARD_VERSION` in `frontend/warm-welcome-card.js` — all three must
  stay identical.
  The card version is appended to the resource URL for cache busting, so
  stale-card bugs appear if it is forgotten. Changes outside the component
  (docs, tests, tooling) need no bump.
- **Keep the README updated**: whenever a change adds, removes, or alters
  user-facing behavior (config flow, entities, attributes, card options),
  update `README.md` in the same commit.
- **Commit per working milestone**: no commits for intermediate debug steps;
  commit subjects mention the new version, e.g. `Fix forecast fallback (0.1.11)`.
- All user-facing temperatures follow the HA unit system (°C or °F) — never
  hardcode a unit.
- Releases are GitHub releases tagged `v<version>`; a workflow stamps the
  manifest and uploads the zip HACS installs.
