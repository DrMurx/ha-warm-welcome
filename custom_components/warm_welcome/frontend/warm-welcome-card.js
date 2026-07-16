/**
 * Warm Welcome card, bundled with the warm_welcome integration.
 *
 * Works without configuration: the card subscribes to the integration's
 * websocket API and shows every room's predicted temperature curve from
 * its computed heating start to the arrival, the shared outdoor forecast
 * on the same temperature axis, and a marker at the vacation end.
 *
 * Optional configuration (all editable in the visual editor):
 *   title: Vacation re-heat     # card header
 *   rooms:                      # subset + line colors (default: all rooms)
 *     - name: Living room
 *       color: "#e67e22"
 *   show_forecast: false        # hide the outdoor forecast (default true)
 *   show_legend: false          # hide the legend (default true)
 *   legend_position: top        # top | bottom (default bottom)
 *   y_min: 10                   # fix the temperature axis (default: auto)
 *   y_max: 25
 *   days: 7                     # fixed time axis of N days from now
 *                               # (default: auto-scale to the arrival,
 *                               # or to the forecast when none is set)
 */

const CARD_VERSION = "0.1.24";

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
  .legend.top { margin-top: 0; margin-bottom: 8px; }
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
      "Could not connect to the Warm Welcome integration. Is it installed and set up?",
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
      "Keine Verbindung zur Integration „Warmer Empfang“. Ist sie installiert und eingerichtet?",
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
      "Kan geen verbinding maken met de integratie Warm welkom. Is deze geïnstalleerd en ingesteld?",
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
      "Impossible de se connecter à l'intégration Accueil chaleureux. Est-elle installée et configurée ?",
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
      "No se pudo conectar con la integración Bienvenida cálida. ¿Está instalada y configurada?",
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
      "Não foi possível ligar à integração Boas-vindas calorosas. Está instalada e configurada?",
    idle: "Sem reaquecimento previsto. Define uma data futura de fim das férias para ver a previsão.",
    arrival: "Chegada",
    heating: "a aquecer",
    starts: "começa {when}",
    beyond_forecast: "A previsão estende-se além da previsão meteorológica disponível",
    outdoor: "Previsão exterior",
  },
};

// Strings of the visual config editor, same fallback rules as STRINGS.
const EDITOR_STRINGS = {
  en: {
    title: "Title",
    rooms: "Rooms",
    rooms_hint: "Choose which rooms to show and their line color.",
    rooms_loading: "Loading rooms…",
    no_rooms: "No rooms found. Set up the Warm Welcome integration first.",
    missing: "(not found)",
    forecast: "Show outdoor forecast",
    legend: "Legend",
    legend_hidden: "Hidden",
    legend_top: "Above the chart",
    legend_bottom: "Below the chart",
    y_axis: "Temperature axis",
    y_min: "Lower limit",
    y_max: "Upper limit",
    auto: "Auto",
    x_axis: "Time axis",
    days: "Days",
  },
  de: {
    title: "Titel",
    rooms: "Räume",
    rooms_hint: "Wähle, welche Räume angezeigt werden und ihre Linienfarbe.",
    rooms_loading: "Räume werden geladen…",
    no_rooms:
      "Keine Räume gefunden. Richte zuerst die Integration „Warmer Empfang“ ein.",
    missing: "(nicht gefunden)",
    forecast: "Außentemperatur-Vorhersage anzeigen",
    legend: "Legende",
    legend_hidden: "Ausgeblendet",
    legend_top: "Über dem Diagramm",
    legend_bottom: "Unter dem Diagramm",
    y_axis: "Temperaturachse",
    y_min: "Untergrenze",
    y_max: "Obergrenze",
    auto: "Auto",
    x_axis: "Zeitachse",
    days: "Tage",
  },
  nl: {
    title: "Titel",
    rooms: "Kamers",
    rooms_hint: "Kies welke kamers worden getoond en hun lijnkleur.",
    rooms_loading: "Kamers laden…",
    no_rooms:
      "Geen kamers gevonden. Stel eerst de integratie Warm welkom in.",
    missing: "(niet gevonden)",
    forecast: "Buitentemperatuurverwachting tonen",
    legend: "Legenda",
    legend_hidden: "Verborgen",
    legend_top: "Boven de grafiek",
    legend_bottom: "Onder de grafiek",
    y_axis: "Temperatuuras",
    y_min: "Ondergrens",
    y_max: "Bovengrens",
    auto: "Auto",
    x_axis: "Tijdas",
    days: "Dagen",
  },
  fr: {
    title: "Titre",
    rooms: "Pièces",
    rooms_hint: "Choisissez les pièces à afficher et la couleur de leur courbe.",
    rooms_loading: "Chargement des pièces…",
    no_rooms:
      "Aucune pièce trouvée. Configurez d'abord l'intégration Accueil chaleureux.",
    missing: "(introuvable)",
    forecast: "Afficher les prévisions extérieures",
    legend: "Légende",
    legend_hidden: "Masquée",
    legend_top: "Au-dessus du graphique",
    legend_bottom: "Sous le graphique",
    y_axis: "Axe des températures",
    y_min: "Limite basse",
    y_max: "Limite haute",
    auto: "Auto",
    x_axis: "Axe du temps",
    days: "Jours",
  },
  es: {
    title: "Título",
    rooms: "Habitaciones",
    rooms_hint: "Elige qué habitaciones mostrar y el color de su línea.",
    rooms_loading: "Cargando habitaciones…",
    no_rooms:
      "No se encontraron habitaciones. Configura primero la integración Bienvenida cálida.",
    missing: "(no encontrada)",
    forecast: "Mostrar previsión exterior",
    legend: "Leyenda",
    legend_hidden: "Oculta",
    legend_top: "Encima del gráfico",
    legend_bottom: "Debajo del gráfico",
    y_axis: "Eje de temperatura",
    y_min: "Límite inferior",
    y_max: "Límite superior",
    auto: "Auto",
    x_axis: "Eje de tiempo",
    days: "Días",
  },
  pt: {
    title: "Título",
    rooms: "Divisões",
    rooms_hint: "Escolhe que divisões mostrar e a cor da sua linha.",
    rooms_loading: "A carregar divisões…",
    no_rooms:
      "Nenhuma divisão encontrada. Configura primeiro a integração Boas-vindas calorosas.",
    missing: "(não encontrada)",
    forecast: "Mostrar previsão exterior",
    legend: "Legenda",
    legend_hidden: "Oculta",
    legend_top: "Acima do gráfico",
    legend_bottom: "Abaixo do gráfico",
    y_axis: "Eixo de temperatura",
    y_min: "Limite inferior",
    y_max: "Limite superior",
    auto: "Auto",
    x_axis: "Eixo de tempo",
    days: "Dias",
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

class WarmWelcomeCard extends HTMLElement {
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

  static getConfigElement() {
    return document.createElement("warm-welcome-card-editor");
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
        { type: "warm_welcome/subscribe" }
      );
    } catch (err) {
      console.error("warm_welcome: subscription failed:", err);
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
      console.error("warm_welcome: render failed:", err);
      this.shadowRoot.innerHTML = "";
      const pre = document.createElement("pre");
      pre.style.whiteSpace = "pre-wrap";
      pre.style.padding = "12px";
      pre.textContent = `warm-welcome-card render error:\n${err?.stack || err}`;
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

    const rawArrival = this._data.arrival
      ? Date.parse(this._data.arrival)
      : null;
    const arrival = rawArrival && rawArrival > Date.now() ? rawArrival : null;
    const rooms = this._selectRooms(this._data.rooms || []);

    // Without an upcoming re-heat the chart still shows the outdoor
    // forecast, with the idle hint above it; the chart is only null
    // when there is no data to plot at all.
    const chart = this._chart(rooms, arrival);
    if (!arrival || !rooms.length) {
      content.append(this._message(this._tr("idle")));
    }
    if (!chart) return;

    const showLegend = this._config.show_legend !== false;
    const legendTop = this._config.legend_position === "top";
    if (showLegend && legendTop) content.append(this._legend(rooms, true));
    content.append(chart);
    if (showLegend && !legendTop) content.append(this._legend(rooms, false));
  }

  // Apply the optional `rooms` config: subset, order and colors. Entries
  // may be plain names or {name, color}; unlisted colors fall back to the
  // palette by display index.
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
    const now = Date.now();
    const days = this._number(this._config.days);
    const forecastAll =
      this._config.show_forecast === false
        ? []
        : (this._data.forecast || []).map((point) => ({
            ts: Date.parse(point.datetime),
            t: point.temperature,
          }));
    let t0, t1;
    if (days !== null && days > 0) {
      t0 = now;
      t1 = now + days * 24 * HOUR;
    } else {
      // Auto: from now (or the earliest heating start) to the arrival;
      // without an upcoming arrival, span the outdoor forecast instead.
      t0 = Math.min(now, ...rooms.map((room) => room.startTs));
      t1 =
        arrival ??
        Math.max(now + 24 * HOUR, ...forecastAll.map((point) => point.ts));
      const pad = (t1 - t0) * 0.03;
      t0 -= pad;
      t1 += pad;
    }

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
      // Nothing inside a fixed window: scale to the full data instead.
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

    // With a fixed time axis or fixed temperature limits the curves can
    // extend beyond the plot area; clip them to it.
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

  // Keep the points inside [t0, t1] plus one neighbor on each side, so
  // the (clipped) line still reaches the plot edges.
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
    // Start marker.
    const [startX, startY] = points[0].split(",");
    parent.append(
      svgEl("circle", {
        cx: startX, cy: startY, r: "4.5", fill: room.color,
        stroke: "var(--card-background-color, #fff)", "stroke-width": "1.5",
      })
    );
  }

  /* ---------- legend ---------- */

  _legend(rooms, top) {
    const legend = document.createElement("div");
    legend.className = top ? "legend top" : "legend";
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

/* ---------- config editor ---------- */

const EDITOR_CSS = `
  :host { display: block; }
  .group { margin: 0 0 20px; }
  .head {
    font-weight: 500;
    margin-bottom: 6px;
    color: var(--primary-text-color, #212121);
  }
  .hint {
    color: var(--secondary-text-color, #727272);
    font-size: 0.85em;
    margin-top: 4px;
  }
  .row { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
  .row > label { flex: 1; }
  input[type="text"], input[type="number"], select {
    box-sizing: border-box;
    padding: 8px 10px;
    color: var(--primary-text-color, #212121);
    background: var(
      --mdc-text-field-fill-color,
      var(--secondary-background-color, #f5f5f5)
    );
    border: none;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 4px 4px 0 0;
    font: inherit;
  }
  input[type="text"] { width: 100%; }
  input[type="number"] { width: 96px; }
  input[type="color"] {
    width: 32px; height: 24px; padding: 0; border: none;
    background: none; cursor: pointer; flex: none;
  }
  input[type="color"]:disabled { opacity: 0.3; cursor: default; }
  .room { display: flex; align-items: center; gap: 10px; margin: 6px 0; }
  .room > label {
    flex: 1; display: flex; align-items: center; gap: 10px;
    cursor: pointer;
  }
  .missing { color: var(--error-color, #db4437); font-size: 0.85em; }
`;

class WarmWelcomeCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._rooms = null; // available room names; null while loading
    this._unsub = null;
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    // Skip the re-render when HA echoes our own config-changed event
    // back, so text inputs keep their focus while typing.
    if (JSON.stringify(this._config) === this._emitted) return;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._loadRooms();
  }

  disconnectedCallback() {
    this._stopLoading();
  }

  // One-shot fetch of the room names through the card's subscription:
  // take the first push, then unsubscribe.
  async _loadRooms() {
    if (!this._hass || this._rooms !== null || this._loading) return;
    this._loading = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (data) => {
          this._rooms = (data.rooms || []).map((room) => room.name);
          this._stopLoading();
          this._render();
        },
        { type: "warm_welcome/subscribe" }
      );
      if (this._rooms !== null || !this.isConnected) this._stopLoading();
    } catch (err) {
      console.error("warm_welcome: editor subscription failed:", err);
      this._rooms = [];
      this._render();
    }
  }

  _stopLoading() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  _tr(key) {
    const lang = (this._hass?.locale?.language || navigator.language || "en")
      .split("-")[0]
      .toLowerCase();
    return (EDITOR_STRINGS[lang] || EDITOR_STRINGS.en)[key] ?? EDITOR_STRINGS.en[key];
  }

  // Merge a patch into the config and notify HA; `undefined` deletes the
  // key, keeping the stored YAML free of defaults.
  _update(patch) {
    const config = { ...this._config };
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined) delete config[key];
      else config[key] = value;
    }
    this._config = config;
    this._emitted = JSON.stringify(config);
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config },
        bubbles: true,
        composed: true,
      })
    );
  }

  /* rendering */

  _render() {
    const root = this.shadowRoot;
    root.innerHTML = "";
    const style = document.createElement("style");
    style.textContent = EDITOR_CSS;
    root.append(style);
    root.append(
      this._titleGroup(),
      this._roomsGroup(),
      this._displayGroup(),
      this._yAxisGroup(),
      this._xAxisGroup()
    );
  }

  _group(title) {
    const group = document.createElement("div");
    group.className = "group";
    if (title) {
      const head = document.createElement("div");
      head.className = "head";
      head.textContent = title;
      group.append(head);
    }
    return group;
  }

  _hint(text) {
    const hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = text;
    return hint;
  }

  _titleGroup() {
    const group = this._group(this._tr("title"));
    const input = document.createElement("input");
    input.type = "text";
    input.value = this._config.title || "";
    input.addEventListener("input", () => {
      this._update({ title: input.value || undefined });
    });
    group.append(input);
    return group;
  }

  /* rooms */

  // The configured rooms normalized to [{name, color?}], or null when
  // the config shows all rooms (no `rooms` key).
  _configuredRooms() {
    if (!Array.isArray(this._config.rooms)) return null;
    return this._config.rooms
      .map((entry) => (typeof entry === "string" ? { name: entry } : entry))
      .filter((entry) => entry && entry.name);
  }

  _roomsGroup() {
    const group = this._group(this._tr("rooms"));
    if (this._rooms === null) {
      group.append(this._hint(this._tr("rooms_loading")));
      return group;
    }
    const configured = this._configuredRooms();
    // Also list configured rooms that no longer exist (e.g. renamed), so
    // they can be unchecked.
    const names = [...this._rooms];
    for (const entry of configured || []) {
      if (!names.includes(entry.name)) names.push(entry.name);
    }
    if (!names.length) {
      group.append(this._hint(this._tr("no_rooms")));
      return group;
    }
    names.forEach((name, index) => {
      const entry = configured?.find((e) => e.name === name);
      const checked = configured ? !!entry : true;
      group.append(
        this._roomRow(
          name,
          checked,
          entry?.color || ROOM_COLORS[index % ROOM_COLORS.length],
          !this._rooms.includes(name)
        )
      );
    });
    group.append(this._hint(this._tr("rooms_hint")));
    return group;
  }

  _roomRow(name, checked, color, missing) {
    const row = document.createElement("div");
    row.className = "room";
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = checked;
    checkbox.addEventListener("change", () => {
      this._changeRoom(name, { checked: checkbox.checked });
      this._render(); // color input enabled state may change
    });
    const text = document.createElement("span");
    text.textContent = name;
    label.append(checkbox, text);
    if (missing) {
      const note = document.createElement("span");
      note.className = "missing";
      note.textContent = this._tr("missing");
      label.append(note);
    }
    const colorInput = document.createElement("input");
    colorInput.type = "color";
    colorInput.value = color;
    colorInput.disabled = !checked;
    colorInput.addEventListener("change", () => {
      this._changeRoom(name, { color: colorInput.value });
    });
    row.append(label, colorInput);
    return row;
  }

  // Any change in the rooms section materializes an explicit `rooms`
  // list (names + colors), so later integration-side room changes no
  // longer reshuffle the selection or the colors.
  _changeRoom(name, patch) {
    const configured = this._configuredRooms();
    let entries = (configured || (this._rooms || []).map((n) => ({ name: n })))
      .map((entry, index) => ({
        name: entry.name,
        color: entry.color || ROOM_COLORS[index % ROOM_COLORS.length],
      }));
    if (patch.checked === false) {
      entries = entries.filter((entry) => entry.name !== name);
    } else if (patch.checked && !entries.some((entry) => entry.name === name)) {
      entries.push({
        name,
        color: ROOM_COLORS[entries.length % ROOM_COLORS.length],
      });
    }
    if (patch.color) {
      const entry = entries.find((e) => e.name === name);
      if (entry) entry.color = patch.color;
    }
    this._update({ rooms: entries });
  }

  /* forecast + legend */

  _displayGroup() {
    const group = this._group();

    const row = document.createElement("div");
    row.className = "row";
    const label = document.createElement("label");
    label.style.cursor = "pointer";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = this._config.show_forecast !== false;
    checkbox.addEventListener("change", () => {
      this._update({ show_forecast: checkbox.checked ? undefined : false });
    });
    label.append(checkbox, document.createTextNode(` ${this._tr("forecast")}`));
    row.append(label);
    group.append(row);

    const legendRow = document.createElement("div");
    legendRow.className = "row";
    const legendLabel = document.createElement("label");
    legendLabel.textContent = this._tr("legend");
    const select = document.createElement("select");
    for (const [value, key] of [
      ["bottom", "legend_bottom"],
      ["top", "legend_top"],
      ["hidden", "legend_hidden"],
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = this._tr(key);
      select.append(option);
    }
    select.value =
      this._config.show_legend === false
        ? "hidden"
        : this._config.legend_position === "top"
          ? "top"
          : "bottom";
    select.addEventListener("change", () => {
      this._update({
        show_legend: select.value === "hidden" ? false : undefined,
        legend_position: select.value === "top" ? "top" : undefined,
      });
    });
    legendRow.append(legendLabel, select);
    group.append(legendRow);
    return group;
  }

  /* axes */

  _yAxisGroup() {
    const group = this._group(this._tr("y_axis"));
    for (const key of ["y_min", "y_max"]) {
      const row = document.createElement("div");
      row.className = "row";
      const label = document.createElement("label");
      label.textContent = this._tr(key);
      const input = document.createElement("input");
      input.type = "number";
      input.step = "0.5";
      input.placeholder = this._tr("auto");
      if (this._config[key] !== undefined && this._config[key] !== null) {
        input.value = this._config[key];
      }
      input.addEventListener("input", () => {
        const value = input.value.trim();
        if (value !== "" && !Number.isFinite(Number(value))) return;
        this._update({ [key]: value === "" ? undefined : Number(value) });
      });
      row.append(label, input);
      group.append(row);
    }
    return group;
  }

  // Like the temperature limits: a plain number field where empty
  // means the automatic window (until arrival / forecast end).
  _xAxisGroup() {
    const group = this._group(this._tr("x_axis"));
    const row = document.createElement("div");
    row.className = "row";
    const label = document.createElement("label");
    label.textContent = this._tr("days");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.placeholder = this._tr("auto");
    if (Number(this._config.days) > 0) input.value = this._config.days;
    input.addEventListener("input", () => {
      const value = input.value.trim();
      if (value === "") {
        this._update({ days: undefined });
        return;
      }
      const days = Number(value);
      if (Number.isFinite(days) && days > 0) this._update({ days });
    });
    row.append(label, input);
    group.append(row);
    return group;
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
const CARD_TAG = "warm-welcome-card";
const EDITOR_TAG = "warm-welcome-card-editor";
const defineStarted = Date.now();

function tryDefineCard() {
  if (window.customElements.get(CARD_TAG)) return true;
  const haReady = !!window.customElements.get("home-assistant");
  // Fall back to defining anyway after 15s (e.g. non-HA pages).
  if (!haReady && Date.now() - defineStarted < 15000) return false;
  window.customElements.define(CARD_TAG, WarmWelcomeCard);
  window.customElements.define(EDITOR_TAG, WarmWelcomeCardEditor);
  return true;
}

if (!tryDefineCard()) {
  const defineInterval = setInterval(() => {
    try {
      if (tryDefineCard()) clearInterval(defineInterval);
    } catch (err) {
      clearInterval(defineInterval);
      console.error("warm_welcome: define failed:", err);
    }
  }, 100);
}

console.info(
  `%c warm_welcome %c card v${CARD_VERSION} `,
  "background: #3f51b5; color: white; font-weight: bold;",
  "background: #eee; color: #333;"
);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "warm-welcome-card",
  name: "Warm Welcome",
  description:
    "Timeline of the predicted re-heat per room, with the outdoor forecast and the vacation end.",
  // No live preview: it depends on an async websocket subscription,
  // which the card picker's preview tile does not handle well.
  preview: false,
});
