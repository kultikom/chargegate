/*
 * ChargeGate dashboard card for Home Assistant
 * https://github.com/kultikom/chargegate
 *
 * Shows all ChargeGate charging points: state (offline / free / charging …), live power as a bar
 * (scaled to the learned maximum of the charging point, e.g. 11 or 22 kW), session duration and the
 * employee charging. Charging points are discovered automatically from the ChargeGate status sensors.
 *
 *   type: custom:chargegate-card
 *   title: Charging points        # optional
 *   site: Head office             # optional: only stations of this site
 *   stations: [DUO-01, EVE-01]    # optional: only these station IDs, in this order
 *   columns: 2                    # optional: fixed number of columns (default: responsive)
 *   show_employee: true           # optional
 */
const CG_VERSION = "1.2.0";

const CG_TEXT = {
  en: {
    title: "Charging points", offline: "Offline", free: "Free", charging: "Charging",
    connected: "Connected", fault: "Fault", unavailable: "Unavailable", reserved: "Reserved",
    connector: "Point", noStations: "No ChargeGate charging points found. Is the MQTT integration set up?",
    charging_now: "{n} charging", of: "of", kw: "kW", since: "since",
  },
  de: {
    title: "Ladepunkte", offline: "Offline", free: "Frei", charging: "Lädt",
    connected: "Verbunden", fault: "Störung", unavailable: "Nicht verfügbar", reserved: "Reserviert",
    connector: "Punkt", noStations: "Keine ChargeGate-Ladepunkte gefunden. Ist die MQTT-Integration eingerichtet?",
    charging_now: "{n} laden", of: "von", kw: "kW", since: "seit",
  },
};

class ChargeGateCard extends HTMLElement {
  setConfig(config) {
    this._config = { show_employee: true, ...(config || {}) };
    this._sig = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return Math.max(3, Math.ceil(this._points().length / 2) * 2);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    const points = this._points();
    const sig = JSON.stringify(points.map((p) => [p.entity_id, p.state, p.attributes])) + hass.language;
    if (sig === this._sig) return;          // nothing relevant changed
    this._sig = sig;
    this._render(points);
  }

  connectedCallback() {
    this._timer = setInterval(() => this._tick(), 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // --- data -----------------------------------------------------------------------------

  _t(key, vars) {
    const lang = (this._hass && this._hass.language || "en").slice(0, 2);
    let s = (CG_TEXT[lang] || CG_TEXT.en)[key] || CG_TEXT.en[key] || key;
    for (const [k, v] of Object.entries(vars || {})) s = s.replace(`{${k}}`, v);
    return s;
  }

  _points() {
    if (!this._hass) return [];
    const cfg = this._config || {};
    const pts = Object.values(this._hass.states).filter(
      (s) => s.attributes && s.attributes.source === "chargegate" && s.attributes.connector !== undefined
        && s.entity_id.startsWith("sensor.")
    );
    return pts.filter((s) => {
      if (cfg.site && s.attributes.site !== cfg.site) return false;
      if (cfg.stations && !cfg.stations.includes(s.attributes.station)) return false;
      return true;
    });
  }

  _stations(points) {
    const byStation = new Map();
    for (const p of points) {
      const a = p.attributes;
      if (!byStation.has(a.station)) {
        byStation.set(a.station, { id: a.station, name: a.station_name || a.station, site: a.site, points: [] });
      }
      byStation.get(a.station).points.push(p);
    }
    let list = [...byStation.values()];
    list.forEach((st) => st.points.sort((x, y) => x.attributes.connector - y.attributes.connector));
    const order = this._config.stations;
    if (order) list.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    else list.sort((a, b) => (a.site || "").localeCompare(b.site || "") || a.name.localeCompare(b.name, undefined, { numeric: true }));
    return list;
  }

  _state(p) {
    const a = p.attributes;
    if (p.state === "unavailable" || !a.online) return "offline";
    if (["Faulted"].includes(a.status)) return "fault";
    if (["Unavailable"].includes(a.status)) return "unavailable";
    if (["Reserved"].includes(a.status)) return "reserved";
    if (a.charging) return (a.power || 0) >= 100 ? "charging" : "connected";
    if (["Preparing", "Occupied", "Finishing", "SuspendedEV", "SuspendedEVSE"].includes(a.status)) return "connected";
    return "free";
  }

  // --- formatting -----------------------------------------------------------------------

  _kw(w) {
    const lang = (this._hass.language || "en").slice(0, 2);
    return (w / 1000).toLocaleString(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  }

  _duration(startIso) {
    if (!startIso) return "";
    const sec = Math.max(0, Math.floor((Date.now() - Date.parse(startIso)) / 1000));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return `${h}:${pad(m)}:${pad(s)}`;
  }

  _esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // --- rendering ------------------------------------------------------------------------

  _tick() {
    if (!this.shadowRoot) return;
    this.shadowRoot.querySelectorAll("[data-start]").forEach((el) => {
      el.textContent = this._duration(el.dataset.start);
    });
  }

  _render(points) {
    const cfg = this._config;
    const stations = this._stations(points);
    const charging = points.filter((p) => this._state(p) === "charging").length;
    const totalW = points.reduce((sum, p) => sum + (p.attributes.online ? (p.attributes.power || 0) : 0), 0);
    const cols = cfg.columns ? `repeat(${Number(cfg.columns)}, minmax(0, 1fr))` : "repeat(auto-fill, minmax(300px, 1fr))";

    const body = stations.length ? stations.map((st) => this._station(st)).join("")
      : `<div class="empty">${this._esc(this._t("noStations"))}</div>`;

    this.shadowRoot.innerHTML = `
      <style>${ChargeGateCard.styles}</style>
      <ha-card>
        <div class="head">
          <div class="title">${this._esc(cfg.title || this._t("title"))}</div>
          <div class="summary">${this._esc(this._t("charging_now", { n: charging }))} · ${this._kw(totalW)} ${this._t("kw")}</div>
        </div>
        <div class="grid" style="grid-template-columns:${cols}">${body}</div>
      </ha-card>`;
  }

  _station(st) {
    const anyOnline = st.points.some((p) => p.attributes.online);
    return `
      <div class="station ${anyOnline ? "" : "is-offline"}">
        <div class="st-head">
          <span class="dot ${anyOnline ? "on" : ""}"></span>
          <span class="st-name">${this._esc(st.name)}</span>
          ${st.site ? `<span class="st-site">${this._esc(st.site)}</span>` : ""}
        </div>
        ${st.points.map((p) => this._point(p, st.points.length > 1)).join("")}
      </div>`;
  }

  _point(p, multi) {
    const a = p.attributes;
    const state = this._state(p);
    const max = a.max_power || 11000;
    const power = state === "offline" ? 0 : (a.power || 0);
    const pct = Math.max(0, Math.min(100, (power / max) * 100));
    const active = a.charging && state !== "offline";
    const employee = this._config.show_employee && a.employee && a.employee !== "–" && active ? a.employee : "";
    return `
      <div class="point s-${state}" data-entity="${this._esc(p.entity_id)}">
        <div class="row1">
          ${multi ? `<span class="num">${a.connector}</span>` : ""}
          <span class="pill">${this._esc(this._t(state))}</span>
          <span class="who" title="${this._esc(employee)}">${this._esc(employee)}</span>
          <span class="dur"${active && a.session_start ? ` data-start="${this._esc(a.session_start)}"` : ""}>${active ? this._duration(a.session_start) : ""}</span>
        </div>
        <div class="row2">
          <div class="bar"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div>
          <span class="kw">${this._kw(power)} <span class="max">/ ${Math.round(max / 1000)} ${this._t("kw")}</span></span>
        </div>
      </div>`;
  }

  static get styles() {
    return `
      :host { --cg-free: var(--success-color, #43a047); --cg-charging: var(--info-color, #039be5);
              --cg-connected: var(--warning-color, #ffa000); --cg-fault: var(--error-color, #db4437);
              --cg-offline: var(--disabled-text-color, #9e9e9e); }
      ha-card { padding: 16px; }
      .head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
      .title { font-size: 1.25em; font-weight: 500; color: var(--primary-text-color); }
      .summary { color: var(--secondary-text-color); font-size: 0.95em; font-variant-numeric: tabular-nums; }
      .grid { display: grid; gap: 12px; }
      .empty { color: var(--secondary-text-color); padding: 8px 0; }
      .station { border: 1px solid var(--divider-color, rgba(127,127,127,.25)); border-radius: 12px; padding: 10px 12px;
                 background: var(--secondary-background-color, transparent); display: flex; flex-direction: column; gap: 8px; }
      .station.is-offline { opacity: .65; }
      .st-head { display: flex; align-items: center; gap: 8px; min-width: 0; }
      .st-name { font-weight: 600; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .st-site { margin-left: auto; color: var(--secondary-text-color); font-size: .85em; white-space: nowrap; }
      .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--cg-offline); flex: none; }
      .dot.on { background: var(--cg-free); }
      .point { display: flex; flex-direction: column; gap: 5px; }
      .row1 { display: flex; align-items: center; gap: 8px; min-width: 0; min-height: 24px; }
      .num { width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
             font-size: .75em; font-weight: 600; color: var(--secondary-text-color); border: 1px solid var(--divider-color, rgba(127,127,127,.3)); flex: none; }
      .pill { font-size: .8em; font-weight: 600; padding: 2px 9px; border-radius: 999px; white-space: nowrap; flex: none;
              color: var(--cg-c); background: color-mix(in srgb, var(--cg-c) 16%, transparent); }
      .who { color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 1; }
      .dur { margin-left: auto; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; white-space: nowrap; font-size: .9em; }
      .row2 { display: flex; align-items: center; gap: 10px; }
      .bar { flex: 1; height: 10px; border-radius: 5px; background: var(--divider-color, rgba(127,127,127,.2)); overflow: hidden; }
      .fill { height: 100%; border-radius: 5px; background: var(--cg-c); transition: width .6s ease; }
      .kw { font-variant-numeric: tabular-nums; white-space: nowrap; font-size: .9em; color: var(--primary-text-color); min-width: 88px; text-align: right; }
      .max { color: var(--secondary-text-color); }
      .s-free { --cg-c: var(--cg-free); }
      .s-charging { --cg-c: var(--cg-charging); }
      .s-charging .fill { background: linear-gradient(90deg, var(--cg-c), color-mix(in srgb, var(--cg-c) 65%, white)); }
      .s-connected, .s-reserved { --cg-c: var(--cg-connected); }
      .s-fault, .s-unavailable { --cg-c: var(--cg-fault); }
      .s-offline { --cg-c: var(--cg-offline); }
    `;
  }
}

if (!customElements.get("chargegate-card")) {
  customElements.define("chargegate-card", ChargeGateCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "chargegate-card",
    name: "ChargeGate",
    description: "All ChargeGate charging points: state, power, session duration and employee.",
    preview: false,
    documentationURL: "https://github.com/kultikom/chargegate/blob/main/docs/home-assistant.md",
  });
  console.info(`%c ChargeGate card ${CG_VERSION} `, "background:#0f7a52;color:#fff;border-radius:4px");
}
