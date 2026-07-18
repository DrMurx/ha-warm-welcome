/**
 * Warm Welcome MOCK card — for README screenshots only, not shipped.
 *
 * A standalone copy of the bundled card that renders a fixed winter
 * scenario instead of subscribing to the integration's websocket. The
 * prediction logic (backward walk with rate interpolation) is ported
 * from heating_model.py so the curves are exactly what the integration
 * would compute for this forecast.
 *
 * Scenario ("now" is frozen at Thursday the 8th, 00:00):
 *   - outdoor temperature meanders around 0 °C over 5 days
 *     (Thu 8 … Mon 12), warmer at daytime, colder at night
 *   - arrival Sunday the 11th, 16:00
 *   - Living room: 14 → 21 °C, Bathroom: 14 → 23 °C, Bedroom: 13.5 → 20 °C
 *
 * Usage: copy to <config>/www/, add /local/warm-welcome-card-mock.js as
 * a dashboard resource (JavaScript module), then add the card:
 *
 *   type: custom:warm-welcome-mock-card
 *   title: Warm Welcome
 *
 * The visual options of the real card (rooms/colors, show_forecast,
 * show_legend, legend_position, y_min, y_max) work the same; the time
 * axis is fixed to the scenario window.
 */

const SVG_NS = "http://www.w3.org/2000/svg";
const WIDTH = 640;
const HEIGHT = 300;
const MARGIN = { left: 48, right: 16, top: 20, bottom: 40 };
const ROOM_COLORS = [
  "#e67e22",
  "#2ecc71",
  "#9b59b6",
  "#e74c3c",
  "#16a085",
  "#f1c40f",
];
const OUTDOOR_COLOR = "#2196f3";
const ARRIVAL_COLOR = "var(--accent-color, #ff9800)";
const HOUR = 36e5;

/* ---------- mock scenario ---------- */

// January 2026: the 8th is a Thursday, the 12th a Monday. The axis
// labels only show weekday + day, so the month never appears.
const MOCK_NOW = new Date(2026, 0, 8, 0, 0).getTime();
const CHART_T0 = MOCK_NOW;
const CHART_T1 = new Date(2026, 0, 12, 23, 30).getTime();
const ARRIVAL = new Date(2026, 0, 11, 16, 0).getTime();

// Hourly outdoor forecast: a diurnal swing around a slowly meandering
// mean near 0 °C, plus small deterministic "noise" so it looks real.
function outdoorAt(hours) {
  const diurnal = 2.8 * Math.sin(((hours - 9.5) / 24) * 2 * Math.PI);
  const drift = 1.1 * Math.sin(hours / 26.7 + 1.3) + 0.7 * Math.sin(hours / 11.9 + 0.4);
  const noise = 0.25 * Math.sin(hours * 2.13) + 0.15 * Math.sin(hours * 0.83);
  return Math.round((diurnal + drift + noise) * 10) / 10;
}

const FORECAST = [];
for (let h = 0; h <= 120; h++) {
  FORECAST.push({ ts: MOCK_NOW + h * HOUR, t: outdoorAt(h) });
}

// Per-room heat rates: [outdoor °C, room °C gained per hour] points, as
// a slow floor heating would measure them — the colder outside, the
// slower the room warms. The bathroom has the strongest loop per m².
const ROOMS = [
  { name: "Living room", current: 14, target: 21, rates: [[-10, 0.14], [0, 0.28], [10, 0.45]] },
  { name: "Bathroom", current: 14, target: 23, rates: [[-10, 0.35], [0, 0.55], [10, 0.80]] },
  { name: "Bedroom", current: 13.5, target: 20, rates: [[-10, 0.16], [0, 0.31], [10, 0.50]] },
];

/* JS port of heating_model.py (rate_at + compute_start, no warmup) */

function rateAt(rates, outdoor) {
  if (outdoor <= rates[0][0]) return rates[0][1];
  if (outdoor >= rates[rates.length - 1][0]) return rates[rates.length - 1][1];
  for (let i = 1; i < rates.length; i++) {
    const [tLow, rLow] = rates[i - 1];
    const [tHigh, rHigh] = rates[i];
    if (outdoor <= tHigh) {
      return rLow + ((outdoor - tLow) / (tHigh - tLow)) * (rHigh - rLow);
    }
  }
}

// Latest forecast point strictly before ``moment``; it defines the
// temperature of the interval ending at ``moment``.
function temperatureBefore(moment) {
  for (let i = FORECAST.length - 1; i >= 0; i--) {
    if (FORECAST[i].ts < moment) return FORECAST[i];
  }
  return FORECAST[0];
}

function computeStart(arrival, current, target, rates) {
  let remaining = target - current;
  let moment = arrival;
  const curve = [{ ts: arrival, t: target }];
  while (remaining > 0) {
    const point = temperatureBefore(moment);
    const rate = rateAt(rates, point.t);
    const gain = rate * ((moment - point.ts) / HOUR);
    if (gain >= remaining) {
      moment -= (remaining / rate) * HOUR;
      remaining = 0;
    } else {
      remaining -= gain;
      moment = point.ts;
    }
    curve.push({ ts: moment, t: current + remaining });
  }
  curve.reverse();
  return { start: moment, curve };
}

// Assembled in the exact shape the websocket API pushes to the card.
const MOCK_DATA = {
  arrival: new Date(ARRIVAL).toISOString(),
  unit: "°C",
  forecast: FORECAST.map((point) => ({
    datetime: new Date(point.ts).toISOString(),
    temperature: point.t,
  })),
  rooms: ROOMS.map((room) => {
    const { start, curve } = computeStart(ARRIVAL, room.current, room.target, room.rates);
    return {
      name: room.name,
      start: new Date(start).toISOString(),
      beyond_forecast: false,
      curve: curve.map((point) => ({
        datetime: new Date(point.ts).toISOString(),
        temperature: Math.round(point.t * 100) / 100,
      })),
    };
  }),
};

/* ---------- card (copy of the real card, websocket removed) ---------- */

const CSS = `
  .content { padding: 0 16px 16px; }
  ha-card[header] .content { padding-top: 0; }
  ha-card:not([header]) .content { padding-top: 16px; }
  svg { width: 100%; height: auto; display: block; }
  .idle {
    color: var(--secondary-text-color);
    padding: 8px 0 4px;
  }
  .legend {
    display: flex; flex-wrap: wrap; gap: 4px 18px;
    margin-top: 8px; font-size: 0.9em;
  }
  .legend.top { margin-top: 0; margin-bottom: 8px; }
  .legend .item { display: flex; align-items: center; gap: 6px; }
  .legend .dot {
    width: 10px; height: 10px; border-radius: 50%; flex: none;
  }
  .legend .when { color: var(--secondary-text-color); }
`;

const STRINGS = {
  en: {
    idle: "No upcoming re-heat",
    arrival: "Arrival",
    heating: "heating",
    starts: "starts {when}",
    beyond_forecast: "Prediction extends beyond the available forecast",
    outdoor: "Outdoor forecast",
  },
  de: {
    idle: "Kein anstehendes Aufheizen",
    arrival: "Ankunft",
    heating: "heizt",
    starts: "startet {when}",
    beyond_forecast: "Die Vorhersage reicht über die verfügbare Wettervorhersage hinaus",
    outdoor: "Außentemperatur-Vorhersage",
  },
};

const STYLE_PROPS = new Set([
  "stroke",
  "fill",
  "opacity",
  "stroke-width",
  "stroke-dasharray",
  "stroke-linejoin",
  "font-size",
  "text-anchor",
]);

function svgEl(tag, attrs = {}, text) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (STYLE_PROPS.has(key)) el.style.setProperty(key, value);
    else el.setAttribute(key, value);
  }
  if (text !== undefined) el.textContent = text;
  return el;
}

function niceStep(raw, steps) {
  for (const step of steps) if (raw <= step) return step;
  return steps[steps.length - 1];
}

class WarmWelcomeMockCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._data = MOCK_DATA;
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  connectedCallback() {
    this._render();
  }

  getCardSize() {
    return 5;
  }

  static getStubConfig() {
    return { title: "Warm Welcome" };
  }

  _locale() {
    return this._hass?.locale?.language || navigator.language;
  }

  _tr(key) {
    const lang = (this._locale() || "en").split("-")[0].toLowerCase();
    return (STRINGS[lang] || STRINGS.en)[key] ?? STRINGS.en[key];
  }

  _fmt(ts, options) {
    return new Intl.DateTimeFormat(this._locale(), options).format(new Date(ts));
  }

  _fmtStart(ts) {
    const options = { weekday: "short", hour: "numeric", minute: "2-digit" };
    if (ts - MOCK_NOW > 6 * 24 * HOUR) {
      options.day = "numeric";
      options.month = "short";
      delete options.weekday;
    }
    return this._fmt(ts, options);
  }

  _render() {
    try {
      this._renderCard();
    } catch (err) {
      console.error("warm_welcome mock: render failed:", err);
      this.shadowRoot.innerHTML = "";
      const pre = document.createElement("pre");
      pre.style.whiteSpace = "pre-wrap";
      pre.style.padding = "12px";
      pre.textContent = `warm-welcome-mock-card render error:\n${err?.stack || err}`;
      this.shadowRoot.append(pre);
    }
  }

  _renderCard() {
    const root = this.shadowRoot;
    root.innerHTML = "";
    const style = document.createElement("style");
    style.textContent = CSS;
    root.append(style);

    const card = document.createElement("ha-card");
    if (this._config.title) card.setAttribute("header", this._config.title);
    const content = document.createElement("div");
    content.className = "content";
    card.append(content);
    root.append(card);

    const rawArrival = this._data.arrival
      ? Date.parse(this._data.arrival)
      : null;
    const arrival = rawArrival && rawArrival > MOCK_NOW ? rawArrival : null;
    const rooms = this._selectRooms(this._data.rooms || []);

    const chart = this._chart(rooms, arrival);
    const idle = !arrival || !rooms.length;
    if (!chart) {
      content.append(this._message(this._tr("idle")));
      return;
    }

    const showLegend = this._config.show_legend !== false;
    const legendTop = this._config.legend_position === "top";
    if (showLegend && legendTop) content.append(this._legend(rooms, true, idle));
    content.append(chart);
    if (showLegend && !legendTop) content.append(this._legend(rooms, false, idle));
  }

  _selectRooms(available) {
    const ready = available.filter((room) => room.start && room.curve.length);
    let rooms = ready;
    if (Array.isArray(this._config.rooms)) {
      rooms = this._config.rooms
        .map((entry) => (typeof entry === "string" ? { name: entry } : entry))
        .filter((entry) => entry && entry.name)
        .map((entry) => {
          const room = ready.find((r) => r.name === entry.name);
          return room ? { ...room, color: entry.color } : null;
        })
        .filter(Boolean);
    }
    return rooms.map((room, index) => ({
      ...room,
      color: room.color || ROOM_COLORS[index % ROOM_COLORS.length],
      startTs: Date.parse(room.start),
    }));
  }

  _message(text) {
    const div = document.createElement("div");
    div.className = "idle";
    div.textContent = text;
    return div;
  }

  /* ---------- chart ---------- */

  _chart(rooms, arrival) {
    // Fixed scenario window instead of the real card's auto/days logic.
    const t0 = CHART_T0;
    const t1 = CHART_T1;
    const forecastAll =
      this._config.show_forecast === false
        ? []
        : (this._data.forecast || []).map((point) => ({
            ts: Date.parse(point.datetime),
            t: point.temperature,
          }));

    const x = (ts) =>
      MARGIN.left +
      ((ts - t0) / (t1 - t0)) * (WIDTH - MARGIN.left - MARGIN.right);

    const forecast = this._clip(forecastAll, t0, t1);

    const inWindow = (ts) => ts >= t0 && ts <= t1;
    let temps = rooms
      .flatMap((room) =>
        room.curve
          .filter((point) => inWindow(Date.parse(point.datetime)))
          .map((point) => point.temperature)
      )
      .concat(
        forecast.filter((point) => inWindow(point.ts)).map((point) => point.t)
      );
    if (!temps.length) {
      temps = rooms
        .flatMap((room) => room.curve.map((point) => point.temperature))
        .concat(forecastAll.map((point) => point.t));
    }
    if (!temps.length) return null;
    const domain = this._domain(temps, 0.5);
    const y = (value) =>
      HEIGHT -
      MARGIN.bottom -
      ((value - domain.lo) / (domain.hi - domain.lo)) *
        (HEIGHT - MARGIN.top - MARGIN.bottom);

    const svg = svgEl("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT}` });

    const clip = svgEl("clipPath", { id: "plot" });
    clip.append(
      svgEl("rect", {
        x: MARGIN.left,
        y: MARGIN.top,
        width: WIDTH - MARGIN.left - MARGIN.right,
        height: HEIGHT - MARGIN.top - MARGIN.bottom,
      })
    );
    const defs = svgEl("defs");
    defs.append(clip);
    svg.append(defs);

    this._drawGridAndAxes(svg, x, y, domain, t0, t1);
    if (forecast.length) {
      const layer = svgEl("g", { "clip-path": "url(#plot)" });
      svg.append(layer);
      this._drawForecast(layer, forecast, x, y);
    }
    if (arrival && inWindow(arrival)) this._drawArrival(svg, x(arrival));
    const roomLayer = svgEl("g", { "clip-path": "url(#plot)" });
    svg.append(roomLayer);
    for (const room of rooms) this._drawRoom(roomLayer, room, x, y);

    return svg;
  }

  _clip(points, t0, t1) {
    return points.filter((point, index) => {
      if (point.ts >= t0 && point.ts <= t1) return true;
      const prev = points[index - 1];
      const next = points[index + 1];
      return (
        (point.ts < t0 && next && next.ts >= t0) ||
        (point.ts > t1 && prev && prev.ts <= t1)
      );
    });
  }

  _number(value) {
    if (value === undefined || value === null || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  _domain(values, minPad) {
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    const pad = Math.max(minPad, (hi - lo) * 0.1);
    lo -= pad;
    hi += pad;
    const yMin = this._number(this._config.y_min);
    const yMax = this._number(this._config.y_max);
    if (yMin !== null) lo = yMin;
    if (yMax !== null) hi = yMax;
    if (hi <= lo) hi = lo + 1;
    return { lo, hi };
  }

  _drawGridAndAxes(svg, x, y, domain, t0, t1) {
    const grid = "var(--divider-color, #e0e0e0)";
    const text = "var(--secondary-text-color, #727272)";
    const font = { "font-size": "11", fill: text };
    const plotBottom = HEIGHT - MARGIN.bottom;

    for (const value of this._ticks(domain.lo, domain.hi)) {
      const yPos = y(value);
      svg.append(
        svgEl("line", {
          x1: MARGIN.left, x2: WIDTH - MARGIN.right, y1: yPos, y2: yPos,
          stroke: grid, "stroke-width": "1",
        }),
        svgEl("text", {
          x: MARGIN.left - 6, y: yPos + 4, "text-anchor": "end", ...font,
        }, `${value}°`)
      );
    }

    const { ticks, daily } = this._xTicks(t0, t1);
    for (const ts of ticks) {
      const options = daily
        ? { weekday: "short", day: "numeric" }
        : { hour: "numeric", minute: "2-digit" };
      svg.append(
        svgEl("line", {
          x1: x(ts), x2: x(ts), y1: plotBottom, y2: plotBottom + 5,
          stroke: text, "stroke-width": "1",
        }),
        svgEl("text", {
          x: x(ts), y: plotBottom + 18, "text-anchor": "middle", ...font,
        }, this._fmt(ts, options))
      );
    }
    svg.append(
      svgEl("line", {
        x1: MARGIN.left, x2: WIDTH - MARGIN.right,
        y1: plotBottom, y2: plotBottom,
        stroke: text, "stroke-width": "1",
      })
    );
  }

  _ticks(lo, hi) {
    const step = niceStep((hi - lo) / 4, [0.5, 1, 2, 5, 10, 20, 50]);
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      ticks.push(Math.round(v * 10) / 10);
    }
    return ticks;
  }

  _xTicks(t0, t1) {
    const stepHours = niceStep((t1 - t0) / HOUR / 6, [1, 2, 3, 6, 12, 24, 48, 96, 168]);
    const ticks = [];
    const cursor = new Date(t0);
    cursor.setMinutes(0, 0, 0);
    if (stepHours >= 24) {
      cursor.setHours(0, 0, 0, 0);
      while (cursor.getTime() < t0) cursor.setDate(cursor.getDate() + 1);
      for (; cursor.getTime() <= t1; cursor.setDate(cursor.getDate() + stepHours / 24)) {
        ticks.push(cursor.getTime());
      }
    } else {
      while (cursor.getTime() < t0 || cursor.getHours() % stepHours) {
        cursor.setTime(cursor.getTime() + HOUR);
      }
      for (; cursor.getTime() <= t1; cursor.setTime(cursor.getTime() + stepHours * HOUR)) {
        ticks.push(cursor.getTime());
      }
    }
    return { ticks, daily: stepHours >= 24 };
  }

  _drawForecast(parent, forecast, x, y) {
    const line = forecast
      .map((point) => `${x(point.ts)},${y(point.t)}`)
      .join(" ");
    const baseline = HEIGHT - MARGIN.bottom;
    const first = forecast[0];
    const last = forecast[forecast.length - 1];
    parent.append(
      svgEl("polygon", {
        points: `${x(first.ts)},${baseline} ${line} ${x(last.ts)},${baseline}`,
        fill: OUTDOOR_COLOR, opacity: "0.08",
      }),
      svgEl("polyline", {
        points: line, fill: "none", stroke: OUTDOOR_COLOR,
        "stroke-width": "1.5", "stroke-dasharray": "5 3",
      })
    );
  }

  _drawArrival(svg, xPos) {
    svg.append(
      svgEl("line", {
        x1: xPos, x2: xPos, y1: MARGIN.top - 4, y2: HEIGHT - MARGIN.bottom,
        stroke: ARRIVAL_COLOR, "stroke-width": "1.5", "stroke-dasharray": "3 3",
      }),
      svgEl("text", {
        x: xPos - 5, y: MARGIN.top + 4, "text-anchor": "end",
        "font-size": "11", fill: ARRIVAL_COLOR,
      }, this._tr("arrival"))
    );
  }

  _drawRoom(parent, room, x, y) {
    const points = room.curve.map(
      (point) => `${x(Date.parse(point.datetime))},${y(point.temperature)}`
    );
    if (points.length > 1) {
      parent.append(
        svgEl("polyline", {
          points: points.join(" "), fill: "none", stroke: room.color,
          "stroke-width": "2.5", "stroke-linejoin": "round",
        })
      );
    }
    const [startX, startY] = points[0].split(",");
    parent.append(
      svgEl("circle", {
        cx: startX, cy: startY, r: "4.5", fill: room.color,
        stroke: "var(--card-background-color, #fff)", "stroke-width": "1.5",
      })
    );
  }

  /* ---------- legend ---------- */

  _legend(rooms, top, idle) {
    const legend = document.createElement("div");
    legend.className = top ? "legend top" : "legend";
    if (idle) {
      const item = document.createElement("div");
      item.className = "item";
      const label = document.createElement("span");
      label.className = "when";
      label.textContent = this._tr("idle");
      item.append(label);
      legend.append(item);
    }
    for (const room of rooms) {
      const item = document.createElement("div");
      item.className = "item";
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = room.color;
      const name = document.createElement("span");
      name.textContent = room.name;
      const when = document.createElement("span");
      when.className = "when";
      when.textContent =
        room.startTs <= MOCK_NOW
          ? this._tr("heating")
          : this._tr("starts").replace("{when}", this._fmtStart(room.startTs));
      if (room.beyond_forecast) {
        when.textContent += " ⚠";
        when.title = this._tr("beyond_forecast");
      }
      item.append(dot, name, when);
      legend.append(item);
    }
    if (this._config.show_forecast !== false) {
      const outdoor = document.createElement("div");
      outdoor.className = "item";
      const dash = document.createElement("span");
      dash.className = "dot";
      dash.style.background = OUTDOOR_COLOR;
      dash.style.opacity = "0.7";
      const label = document.createElement("span");
      label.className = "when";
      label.textContent = this._tr("outdoor");
      outdoor.append(dash, label);
      legend.append(outdoor);
    }
    return legend;
  }
}

/* Deferred registration, same reason as the real card: wait for HA's
 * custom-element registry swap before defining. */
const CARD_TAG = "warm-welcome-mock-card";
const defineStarted = Date.now();

function tryDefineCard() {
  if (window.customElements.get(CARD_TAG)) return true;
  const haReady = !!window.customElements.get("home-assistant");
  if (!haReady && Date.now() - defineStarted < 15000) return false;
  window.customElements.define(CARD_TAG, WarmWelcomeMockCard);
  return true;
}

if (!tryDefineCard()) {
  const defineInterval = setInterval(() => {
    try {
      if (tryDefineCard()) clearInterval(defineInterval);
    } catch (err) {
      clearInterval(defineInterval);
      console.error("warm_welcome mock: define failed:", err);
    }
  }, 100);
}

console.info(
  "%c warm_welcome %c mock card (screenshot data) ",
  "background: #3f51b5; color: white; font-weight: bold;",
  "background: #eee; color: #333;"
);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "warm-welcome-mock-card",
  name: "Warm Welcome (Mock)",
  description: "Screenshot mock of the Warm Welcome card with fixed winter data.",
  preview: false,
});
