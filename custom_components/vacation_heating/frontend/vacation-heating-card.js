/**
 * Vacation Heating card, bundled with the vacation_heating integration.
 *
 * Zero configuration: the card subscribes to the integration's websocket
 * API and shows every room's predicted temperature curve from its
 * computed heating start to the arrival, the shared outdoor forecast on
 * the same temperature axis, and a marker at the vacation end.
 */

const CARD_VERSION = "0.1.14";

const SVG_NS = "http://www.w3.org/2000/svg";
const WIDTH = 640;
const HEIGHT = 300;
const MARGIN = { left: 48, right: 16, top: 20, bottom: 40 };
// No blue: the outdoor forecast owns that hue.
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
  .legend .item { display: flex; align-items: center; gap: 6px; }
  .legend .dot {
    width: 10px; height: 10px; border-radius: 50%; flex: none;
  }
  .legend .when { color: var(--secondary-text-color); }
`;

// UI strings per language ({when} is replaced with the formatted start
// time). Falls back to English for unlisted languages.
const STRINGS = {
  en: {
    loading: "Loading…",
    error:
      "Could not connect to the Vacation Heating integration. Is it installed and set up?",
    idle: "No upcoming re-heat. Set a future vacation end date to see the prediction.",
    arrival: "Arrival",
    heating: "heating",
    starts: "starts {when}",
    beyond_forecast: "Prediction extends beyond the available forecast",
    outdoor: "Outdoor forecast",
  },
  de: {
    loading: "Wird geladen…",
    error:
      "Keine Verbindung zur Urlaubsheizung-Integration. Ist sie installiert und eingerichtet?",
    idle: "Kein anstehendes Aufheizen. Setze ein zukünftiges Urlaubsende, um die Vorhersage zu sehen.",
    arrival: "Ankunft",
    heating: "heizt",
    starts: "startet {when}",
    beyond_forecast: "Die Vorhersage reicht über die verfügbare Wettervorhersage hinaus",
    outdoor: "Außentemperatur-Vorhersage",
  },
  nl: {
    loading: "Laden…",
    error:
      "Kan geen verbinding maken met de Vakantieverwarming-integratie. Is deze geïnstalleerd en ingesteld?",
    idle: "Geen aankomende opwarming. Stel een toekomstig einde van de vakantie in om de voorspelling te zien.",
    arrival: "Aankomst",
    heating: "verwarmt",
    starts: "start {when}",
    beyond_forecast: "De voorspelling reikt verder dan de beschikbare weersverwachting",
    outdoor: "Buitentemperatuurverwachting",
  },
  fr: {
    loading: "Chargement…",
    error:
      "Impossible de se connecter à l'intégration Chauffage vacances. Est-elle installée et configurée ?",
    idle: "Aucun réchauffage à venir. Définissez une date de fin de vacances future pour voir la prédiction.",
    arrival: "Arrivée",
    heating: "chauffe",
    starts: "démarre {when}",
    beyond_forecast: "La prédiction s'étend au-delà des prévisions disponibles",
    outdoor: "Prévisions extérieures",
  },
  es: {
    loading: "Cargando…",
    error:
      "No se pudo conectar con la integración Calefacción de vacaciones. ¿Está instalada y configurada?",
    idle: "No hay recalentamiento próximo. Establece una fecha futura de fin de vacaciones para ver la predicción.",
    arrival: "Llegada",
    heating: "calentando",
    starts: "empieza {when}",
    beyond_forecast: "La predicción se extiende más allá de la previsión disponible",
    outdoor: "Previsión exterior",
  },
  pt: {
    loading: "A carregar…",
    error:
      "Não foi possível ligar à integração Aquecimento de férias. Está instalada e configurada?",
    idle: "Sem reaquecimento previsto. Define uma data futura de fim das férias para ver a previsão.",
    arrival: "Chegada",
    heating: "a aquecer",
    starts: "começa {when}",
    beyond_forecast: "A previsão estende-se além da previsão meteorológica disponível",
    outdoor: "Previsão exterior",
  },
};

// Paint properties must be set as CSS: var() references are invalid in
// SVG presentation attributes (the stroke silently becomes 'none').
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

class VacationHeatingCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._data = null;
    this._error = null;
    this._unsub = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._subscribe();
  }

  connectedCallback() {
    this._connected = true;
    this._subscribe();
  }

  disconnectedCallback() {
    this._connected = false;
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  getCardSize() {
    return 5;
  }

  static getStubConfig() {
    return {};
  }

  async _subscribe() {
    if (!this._connected || !this._hass || this._unsub || this._subscribing) {
      return;
    }
    this._subscribing = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (data) => {
          this._data = data;
          this._error = null;
          this._render();
        },
        { type: "vacation_heating/subscribe" }
      );
    } catch (err) {
      console.error("vacation_heating: subscription failed:", err);
      this._error = true;
      this._render();
    } finally {
      this._subscribing = false;
    }
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
    if (ts - Date.now() > 6 * 24 * HOUR) {
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
      console.error("vacation_heating: render failed:", err);
      this.shadowRoot.innerHTML = "";
      const pre = document.createElement("pre");
      pre.style.whiteSpace = "pre-wrap";
      pre.style.padding = "12px";
      pre.textContent = `vacation-heating-card render error:\n${err?.stack || err}`;
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

    if (this._error) {
      content.append(this._message(this._tr("error")));
      return;
    }
    if (!this._data) {
      content.append(this._message(this._tr("loading")));
      return;
    }

    const arrival = this._data.arrival ? Date.parse(this._data.arrival) : null;
    const rooms = (this._data.rooms || [])
      .filter((room) => room.start && room.curve.length)
      .map((room, index) => ({
        ...room,
        color: ROOM_COLORS[index % ROOM_COLORS.length],
        startTs: Date.parse(room.start),
      }));

    if (!arrival || arrival <= Date.now() || !rooms.length) {
      content.append(this._message(this._tr("idle")));
      return;
    }

    content.append(this._chart(rooms, arrival));
    content.append(this._legend(rooms));
  }

  _message(text) {
    const div = document.createElement("div");
    div.className = "idle";
    div.textContent = text;
    return div;
  }

  /* ---------- chart ---------- */

  _chart(rooms, arrival) {
    const now = Date.now();
    let t0 = Math.min(now, ...rooms.map((room) => room.startTs));
    let t1 = arrival;
    const pad = (t1 - t0) * 0.03;
    t0 -= pad;
    t1 += pad;

    const x = (ts) =>
      MARGIN.left +
      ((ts - t0) / (t1 - t0)) * (WIDTH - MARGIN.left - MARGIN.right);

    const forecast = (this._data.forecast || [])
      .map((point) => ({ ts: Date.parse(point.datetime), t: point.temperature }))
      .filter((point) => point.ts >= t0 && point.ts <= t1);

    const temps = rooms
      .flatMap((room) => room.curve.map((point) => point.temperature))
      .concat(forecast.map((point) => point.t));
    const domain = this._domain(temps, 0.5);
    const y = (value) =>
      HEIGHT -
      MARGIN.bottom -
      ((value - domain.lo) / (domain.hi - domain.lo)) *
        (HEIGHT - MARGIN.top - MARGIN.bottom);

    const svg = svgEl("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT}` });

    this._drawGridAndAxes(svg, x, y, domain, t0, t1);
    if (forecast.length) this._drawForecast(svg, forecast, x, y);
    this._drawArrival(svg, x(arrival));
    for (const room of rooms) this._drawRoom(svg, room, x, y);

    return svg;
  }

  _domain(values, minPad) {
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    const pad = Math.max(minPad, (hi - lo) * 0.1);
    return { lo: lo - pad, hi: hi + pad };
  }

  _drawGridAndAxes(svg, x, y, domain, t0, t1) {
    const grid = "var(--divider-color, #e0e0e0)";
    const text = "var(--secondary-text-color, #727272)";
    const font = { "font-size": "11", fill: text };
    const plotBottom = HEIGHT - MARGIN.bottom;

    // Horizontal grid + temperature labels.
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

    // Time ticks.
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

  _drawForecast(svg, forecast, x, y) {
    const line = forecast
      .map((point) => `${x(point.ts)},${y(point.t)}`)
      .join(" ");
    const baseline = HEIGHT - MARGIN.bottom;
    const first = forecast[0];
    const last = forecast[forecast.length - 1];
    svg.append(
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

  _drawRoom(svg, room, x, y) {
    const points = room.curve.map(
      (point) => `${x(Date.parse(point.datetime))},${y(point.temperature)}`
    );
    if (points.length > 1) {
      svg.append(
        svgEl("polyline", {
          points: points.join(" "), fill: "none", stroke: room.color,
          "stroke-width": "2.5", "stroke-linejoin": "round",
        })
      );
    }
    // Start marker.
    const [startX, startY] = points[0].split(",");
    svg.append(
      svgEl("circle", {
        cx: startX, cy: startY, r: "4.5", fill: room.color,
        stroke: "var(--card-background-color, #fff)", "stroke-width": "1.5",
      })
    );
  }

  /* ---------- legend ---------- */

  _legend(rooms) {
    const legend = document.createElement("div");
    legend.className = "legend";
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
        room.startTs <= Date.now()
          ? this._tr("heating")
          : this._tr("starts").replace("{when}", this._fmtStart(room.startTs));
      if (room.beyond_forecast) {
        when.textContent += " ⚠";
        when.title = this._tr("beyond_forecast");
      }
      item.append(dot, name, when);
      legend.append(item);
    }
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
    return legend;
  }
}

/*
 * Deferred registration. This module races HA's app bundle: HA installs
 * a scoped-custom-element-registry polyfill that REPLACES
 * window.customElements during boot. Defining before that swap puts the
 * element into the native registry, which the polyfilled
 * customElements.get() cannot see — Lovelace then reports "Custom
 * element doesn't exist" although the element upgrades fine. Waiting
 * for HA's own <home-assistant> element guarantees the final registry
 * is in place; look up window.customElements freshly on every attempt.
 */
const CARD_TAG = "vacation-heating-card";
const defineStarted = Date.now();

function tryDefineCard() {
  if (window.customElements.get(CARD_TAG)) return true;
  const haReady = !!window.customElements.get("home-assistant");
  // Fall back to defining anyway after 15s (e.g. non-HA pages).
  if (!haReady && Date.now() - defineStarted < 15000) return false;
  window.customElements.define(CARD_TAG, VacationHeatingCard);
  return true;
}

if (!tryDefineCard()) {
  const defineInterval = setInterval(() => {
    try {
      if (tryDefineCard()) clearInterval(defineInterval);
    } catch (err) {
      clearInterval(defineInterval);
      console.error("vacation_heating: define failed:", err);
    }
  }, 100);
}

console.info(
  `%c vacation_heating %c card v${CARD_VERSION} `,
  "background: #3f51b5; color: white; font-weight: bold;",
  "background: #eee; color: #333;"
);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "vacation-heating-card",
  name: "Vacation Heating",
  description:
    "Timeline of the predicted re-heat per room, with the outdoor forecast and the vacation end.",
  // No live preview: it depends on an async websocket subscription,
  // which the card picker's preview tile does not handle well.
  preview: false,
});
