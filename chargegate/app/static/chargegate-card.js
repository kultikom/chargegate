// SPDX-License-Identifier: BUSL-1.1
// Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
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
 *   site: Head office             # optional: only stations of this site – set in the card editor
 *   sites: [Head office, Depot]   # optional: only stations of these sites
 *   show_site_tabs: false         # optional: let viewers switch between sites with tabs (default: off)
 *   default_site: Head office     # optional, with tabs: tab selected at first
 *   stations: [DUO-01, EVE-01]    # optional: only these station IDs, in this order
 *   columns: 2                    # optional: fixed number of columns (default: responsive)
 *   show_employee: true           # optional
 *   show_soc: true                # optional: battery level, if the station reports it
 */
const CG_VERSION = "1.8.1";

const CG_TEXT = {
  en: {
    title: "Charging points", offline: "Offline", free: "Free", charging: "Charging",
    done: "Done", paused: "Paused", done_for: "for", done_title: "Done for {idle} · session {total}",
    connected: "Connected", fault: "Fault", unavailable: "Unavailable", reserved: "Reserved",
    connector: "Point", noStations: "No ChargeGate charging points found. Is the MQTT integration set up?",
    charging_now: "{n} charging", done_now: "{n} done", of: "of", kw: "kW", since: "since", soc: "Battery",
    all_sites: "All", ed_title: "Title", ed_site: "Site", ed_all_tabs: "All sites (switch with tabs)",
    ed_columns: "Columns", ed_auto: "automatic", ed_employee: "Show employee", ed_soc: "Show battery level",
    ed_tabs: "Viewers may switch sites (tabs)", ed_default: "Tab selected at first",
    ed_all: "All sites",
  },
  de: {
    title: "Ladepunkte", offline: "Offline", free: "Frei", charging: "Lädt",
    done: "Fertig", paused: "Pausiert", done_for: "seit", done_title: "Fertig seit {idle} · Ladedauer {total}",
    connected: "Verbunden", fault: "Störung", unavailable: "Nicht verfügbar", reserved: "Reserviert",
    connector: "Punkt", noStations: "Keine ChargeGate-Ladepunkte gefunden. Ist die MQTT-Integration eingerichtet?",
    charging_now: "{n} laden", done_now: "{n} fertig", of: "von", kw: "kW", since: "seit", soc: "Akkustand",
    all_sites: "Alle", ed_title: "Titel", ed_site: "Standort", ed_all_tabs: "Alle Standorte (mit Reitern umschalten)",
    ed_columns: "Spalten", ed_auto: "automatisch", ed_employee: "Mitarbeiter anzeigen", ed_soc: "Akkustand anzeigen",
    ed_tabs: "Betrachter dürfen den Standort umschalten (Reiter)", ed_default: "Zuerst gewählter Reiter",
    ed_all: "Alle Standorte",
  },
};

class ChargeGateCard extends HTMLElement {
  setConfig(config) {
    this._config = { show_employee: true, show_soc: true, show_site_tabs: false, ...(config || {}) };
    this._sig = null;
    this._selected = undefined;               // site chosen with the tabs (null = all)
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return document.createElement("chargegate-card-editor");
  }

  // --- site tabs ------------------------------------------------------------------------

  _storeKey() {
    return "chargegate-card-site:" + (this._config.title || "") + ":" + (this._config.sites || []).join("|");
  }

  _siteList(points) {
    const names = [...new Set(points.map((p) => p.attributes.site || ""))];
    const order = this._config.sites;
    const list = order ? order.filter((s) => names.includes(s))
      : names.filter((s) => s).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    if (!order && names.includes("")) list.push("");          // stations without a site
    return list;
  }

  _tabsActive(sites) {
    return !this._config.site && this._config.show_site_tabs === true && sites.length > 1;
  }

  _currentSite(sites) {
    if (this._selected === undefined) {
      let saved = null;
      try { saved = window.localStorage.getItem(this._storeKey()); } catch (e) { /* storage blocked */ }
      const wanted = saved !== null ? saved : this._config.default_site;
      this._selected = wanted === "*" || wanted === undefined || wanted === null ? null : wanted;
    }
    return this._selected !== null && sites.includes(this._selected) ? this._selected : null;
  }

  _selectSite(site) {
    this._selected = site;
    try { window.localStorage.setItem(this._storeKey(), site === null ? "*" : site); } catch (e) { /* ignore */ }
    this._sig = null;
    this.hass = this._hass;
  }

  getCardSize() {
    return Math.max(3, Math.ceil(this._points().length / 2) * 2);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    const points = this._allPoints();
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

  _allPoints() {
    if (!this._hass) return [];
    const cfg = this._config || {};
    return Object.values(this._hass.states).filter((s) => {
      const a = s.attributes;
      if (!a || a.source !== "chargegate" || a.connector === undefined || !s.entity_id.startsWith("sensor.")) return false;
      if (cfg.site && a.site !== cfg.site) return false;
      if (cfg.sites && !cfg.sites.includes(a.site)) return false;
      if (cfg.stations && !cfg.stations.includes(a.station)) return false;
      return true;
    });
  }

  _points() {
    const all = this._allPoints();
    const sites = this._siteList(all);
    if (!this._tabsActive(sites)) return all;
    const current = this._currentSite(sites);
    return current === null ? all : all.filter((p) => (p.attributes.site || "") === current);
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
    else list.sort((a, b) => (!a.site - !b.site)                       // stations without a site last
      || (a.site || "").localeCompare(b.site || "", undefined, { numeric: true })
      || a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));
    return list;
  }

  _state(p) {
    const a = p.attributes;
    if (p.state === "unavailable" || !a.online) return "offline";
    if (a.phase) return a.phase;               // ChargeGate 1.5+: decided by the server
    if (["Faulted"].includes(a.status)) return "fault";
    if (["Unavailable"].includes(a.status)) return "unavailable";
    if (["Reserved"].includes(a.status)) return "reserved";
    // The station's own status wins – power is only a hint (not every station reports it)
    if (a.status === "Charging") return "charging";
    if (["Preparing", "Occupied", "Finishing", "SuspendedEV", "SuspendedEVSE"].includes(a.status)) return "connected";
    if (a.charging) return (a.power || 0) >= 100 ? "charging" : "connected";
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
      el.textContent = (el.dataset.prefix ? el.dataset.prefix + " " : "") + this._duration(el.dataset.start);
    });
  }

  _render(allPoints) {
    const cfg = this._config;
    const sites = this._siteList(allPoints);
    const tabs = this._tabsActive(sites);
    const current = tabs ? this._currentSite(sites) : null;
    const points = current === null ? allPoints : allPoints.filter((p) => (p.attributes.site || "") === current);
    const stations = this._stations(points);
    const charging = points.filter((p) => this._state(p) === "charging").length;
    const done = points.filter((p) => this._state(p) === "done").length;
    const totalW = points.reduce((sum, p) => sum + (p.attributes.online ? (p.attributes.power || 0) : 0), 0);
    const cols = cfg.columns ? `repeat(${Number(cfg.columns)}, minmax(0, 1fr))` : "repeat(auto-fill, minmax(300px, 1fr))";

    const body = stations.length ? stations.map((st) => this._station(st)).join("")
      : `<div class="empty">${this._esc(this._t("noStations"))}</div>`;

    this.shadowRoot.innerHTML = `
      <style>${ChargeGateCard.styles}</style>
      <ha-card>
        <div class="head">
          <div class="title">${this._esc(cfg.title || this._t("title"))}</div>
          <div class="summary">${this._esc(this._t("charging_now", { n: charging }))}${done ? " · " + this._esc(this._t("done_now", { n: done })) : ""} · ${this._kw(totalW)} ${this._t("kw")}</div>
        </div>
        ${tabs ? this._tabs(sites, current, allPoints) : ""}
        <div class="grid" style="grid-template-columns:${cols}">${body}</div>
      </ha-card>`;
    this.shadowRoot.querySelectorAll(".tab").forEach((el) => {
      el.addEventListener("click", () => this._selectSite(el.dataset.site === "*" ? null : el.dataset.site));
    });
  }

  _tabs(sites, current, allPoints) {
    const busy = (site) => allPoints.filter((p) => (site === null || (p.attributes.site || "") === site)
      && ["charging", "done", "connected", "paused"].includes(this._state(p))).length;
    const tab = (site, label) => {
      const n = busy(site);
      return `<button class="tab ${current === site ? "on" : ""}" data-site="${site === null ? "*" : this._esc(site)}">
        ${this._esc(label)}${n ? ` <span class="cnt">${n}</span>` : ""}</button>`;
    };
    return `<div class="tabs" role="tablist">${tab(null, this._t("all_sites"))}${
      sites.map((s) => tab(s, s || "–")).join("")}</div>`;
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
          ${multi ? (a.connector_label
            ? `<span class="lbl" title="${this._esc(a.connector_label)}">${this._esc(a.connector_label)}</span>`
            : `<span class="num">${a.connector}</span>`) : ""}
          <span class="pill" title="OCPP: ${this._esc(a.status)}">${state === "done" ? "✓ " : ""}${this._esc(this._t(state))}</span>
          <span class="who" title="${this._esc(employee)}">${this._esc(employee)}</span>
          ${this._soc(a, active)}
          ${this._dur(a, state, active)}
        </div>
        <div class="row2">
          <div class="bar"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div>
          <span class="kw">${this._kw(power)} <span class="max">/ ${Math.round(max / 1000)} ${this._t("kw")}</span></span>
        </div>
      </div>`;
  }

  _dur(a, state, active) {
    if (!active || !a.session_start) return `<span class="dur"></span>`;
    if (state === "done" && a.idle_since) {
      // a finished car: how long has it been standing there full?
      const prefix = this._t("done_for");
      const title = this._t("done_title", { idle: this._duration(a.idle_since), total: this._duration(a.session_start) });
      return `<span class="dur done" data-start="${this._esc(a.idle_since)}" data-prefix="${this._esc(prefix)}"
        title="${this._esc(title)}">${this._esc(prefix)} ${this._duration(a.idle_since)}</span>`;
    }
    return `<span class="dur" data-start="${this._esc(a.session_start)}">${this._duration(a.session_start)}</span>`;
  }

  _soc(a, active) {
    if (!this._config.show_soc || !active || a.soc === null || a.soc === undefined) return "";
    const soc = Math.round(a.soc);
    const from = a.soc_start !== null && a.soc_start !== undefined && a.soc_start < soc ? `${Math.round(a.soc_start)} → ` : "";
    const title = `${this._t("soc")}: ${from}${soc} %`;
    return `<span class="soc" title="${this._esc(title)}">
      <svg viewBox="0 0 24 12" width="22" height="11" aria-hidden="true">
        <rect x="0.75" y="0.75" width="20" height="10.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/>
        <rect x="21.5" y="3.5" width="2" height="5" rx="1" fill="currentColor"/>
        <rect x="2.5" y="2.5" width="${(16.5 * soc / 100).toFixed(1)}" height="7" rx="1" fill="currentColor"/>
      </svg>${soc} %</span>`;
  }

  static get styles() {
    return `
      :host { --cg-free: var(--success-color, #43a047); --cg-charging: var(--info-color, #039be5);
              --cg-connected: var(--warning-color, #ffa000); --cg-done: #00897b; --cg-fault: var(--error-color, #db4437);
              --cg-offline: var(--disabled-text-color, #9e9e9e); }
      ha-card { padding: 16px; }
      .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin: -4px 0 12px; }
      .tab { font: inherit; font-size: .9em; cursor: pointer; border-radius: 999px; padding: 4px 12px;
             border: 1px solid var(--divider-color, rgba(127,127,127,.3)); background: transparent;
             color: var(--secondary-text-color); display: inline-flex; align-items: center; gap: 6px; }
      .tab:hover { color: var(--primary-text-color); }
      .tab.on { background: var(--primary-color, #03a9f4); border-color: var(--primary-color, #03a9f4);
                color: var(--text-primary-color, #fff); }
      .tab .cnt { font-size: .8em; font-weight: 700; min-width: 18px; padding: 0 5px; border-radius: 999px;
                  background: color-mix(in srgb, currentColor 18%, transparent); }
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
      .lbl { font-size: .75em; font-weight: 600; color: var(--secondary-text-color); padding: 1px 7px; border-radius: 999px;
             border: 1px solid var(--divider-color, rgba(127,127,127,.3)); white-space: nowrap; flex: none; max-width: 7em;
             overflow: hidden; text-overflow: ellipsis; }
      .pill { font-size: .8em; font-weight: 600; padding: 2px 9px; border-radius: 999px; white-space: nowrap; flex: none;
              color: var(--cg-c); background: color-mix(in srgb, var(--cg-c) 16%, transparent); }
      .who { color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 1; }
      .soc { display: inline-flex; align-items: center; gap: 4px; font-size: .9em; white-space: nowrap; flex: none;
             color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
      .dur { margin-left: auto; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; white-space: nowrap; font-size: .9em; }
      .row2 { display: flex; align-items: center; gap: 10px; }
      .bar { flex: 1; height: 10px; border-radius: 5px; background: var(--divider-color, rgba(127,127,127,.2)); overflow: hidden; }
      .fill { height: 100%; border-radius: 5px; background: var(--cg-c); transition: width .6s ease; }
      .kw { font-variant-numeric: tabular-nums; white-space: nowrap; font-size: .9em; color: var(--primary-text-color); min-width: 88px; text-align: right; }
      .max { color: var(--secondary-text-color); }
      .s-free { --cg-c: var(--cg-free); }
      .s-done { --cg-c: var(--cg-done); }
      .s-done .pill { font-weight: 700; }
      .dur.done { color: var(--cg-done); font-weight: 600; }
      .s-paused { --cg-c: var(--cg-connected); }
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
    preview: true,
    documentationURL: "https://github.com/kultikom/chargegate/blob/main/docs/home-assistant.md",
  });
  console.info(`%c ChargeGate card ${CG_VERSION} `, "background:#0f7a52;color:#fff;border-radius:4px");
}


// --- visual editor ----------------------------------------------------------------------------

class ChargeGateCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._render();
  }

  _t(key) {
    const lang = (this._hass && this._hass.language || "en").slice(0, 2);
    return (CG_TEXT[lang] || CG_TEXT.en)[key] || CG_TEXT.en[key] || key;
  }

  _sites() {
    if (!this._hass) return [];
    const names = new Set(Object.values(this._hass.states)
      .filter((s) => s.attributes && s.attributes.source === "chargegate" && s.attributes.site)
      .map((s) => s.attributes.site));
    return [...names].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }

  _esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  _render() {
    if (!this._config) return;
    const c = this._config, sites = this._sites();
    const opt = (v, label, sel) => `<option value="${this._esc(v)}" ${sel ? "selected" : ""}>${this._esc(label)}</option>`;
    const check = (key, def) => `<label class="chk"><input type="checkbox" data-key="${key}" ${(c[key] ?? def) ? "checked" : ""}> ${this._esc(this._t("ed_" + { show_employee: "employee", show_soc: "soc", show_site_tabs: "tabs" }[key]))}</label>`;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        .f { display: grid; gap: 12px; padding: 4px 0; }
        label { display: grid; gap: 4px; font-size: 14px; color: var(--primary-text-color); }
        .chk { display: flex; align-items: center; gap: 8px; }
        input[type=text], input[type=number], select { font: inherit; padding: 8px; border-radius: 6px;
          border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color, #fff); color: inherit; }
      </style>
      <div class="f">
        <label>${this._esc(this._t("ed_title"))}<input type="text" data-key="title" value="${this._esc(c.title || "")}" placeholder="${this._esc(this._t("title"))}"></label>
        <label>${this._esc(this._t("ed_site"))}<select data-key="site">
          ${opt("", this._t("ed_all"), !c.site)}${sites.map((s) => opt(s, s, c.site === s)).join("")}</select></label>
        ${c.site ? "" : check("show_site_tabs", false)}
        ${c.site || !c.show_site_tabs ? "" : `<label>${this._esc(this._t("ed_default"))}<select data-key="default_site">
          ${opt("", this._t("all_sites"), !c.default_site)}${sites.map((s) => opt(s, s, c.default_site === s)).join("")}</select></label>`}
        <label>${this._esc(this._t("ed_columns"))}<input type="number" min="1" max="6" data-key="columns" value="${this._esc(c.columns || "")}" placeholder="${this._esc(this._t("ed_auto"))}"></label>
        ${check("show_employee", true)}
        ${check("show_soc", true)}
      </div>`;
    this.shadowRoot.querySelectorAll("[data-key]").forEach((el) => {
      el.addEventListener("change", () => this._changed(el));
    });
  }

  _changed(el) {
    const key = el.dataset.key;
    const cfg = { ...this._config };
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (key === "columns") value = value ? Number(value) : "";
    if (value === "" || value === null) delete cfg[key]; else cfg[key] = value;
    if (key === "site" && value) { delete cfg.default_site; delete cfg.show_site_tabs; }
    this._config = cfg;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: cfg }, bubbles: true, composed: true }));
    if (key === "show_site_tabs" && !value) delete cfg.default_site;
    if (key === "site" || key === "show_site_tabs") this._render();
  }
}

if (!customElements.get("chargegate-card-editor")) {
  customElements.define("chargegate-card-editor", ChargeGateCardEditor);
}
