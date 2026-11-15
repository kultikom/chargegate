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
 *   show_soc: true                # optional: battery level (from the station or the car)
 *   show_vehicle: true            # optional: car, charge limit, range, full at (ChargeGate Vehicles)
 *   view: plan                    # optional: site plan instead of the list (drawn in ChargeGate › Site plan)
 */
const CG_VERSION = "1.15.1";

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
    ed_all: "All sites", ed_vehicle: "Show car (limit, range, full at)",
    limit: "limit {n} %", full_at: "full ~{t}", soc_title: "Battery {soc} % · charge limit {limit} %",
    unknown_point: "unknown", plan_missing: "No site plan yet – draw one in ChargeGate › Site plan.",
    ed_view: "View", ed_view_list: "List", ed_view_plan: "Site plan", no_site: "No site",
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
    ed_all: "Alle Standorte", ed_vehicle: "Fahrzeug anzeigen (Ziel, Reichweite, voll um)",
    limit: "Ziel {n} %", full_at: "voll ~{t}", soc_title: "Akkustand {soc} % · Ladelimit {limit} %",
    unknown_point: "unbekannt", plan_missing: "Noch kein Lageplan – in ChargeGate unter Lageplan zeichnen.",
    ed_view: "Ansicht", ed_view_list: "Liste", ed_view_plan: "Lageplan", no_site: "Ohne Standort",
  },
};

class ChargeGateCard extends HTMLElement {
  setConfig(config) {
    this._config = { show_employee: true, show_soc: true, show_vehicle: true, show_site_tabs: false, ...(config || {}) };
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
    const plans = this._config.view === "plan" ? this._planStates() : [];
    const sig = JSON.stringify(points.map((p) => [p.entity_id, p.state, p.attributes]))
      + JSON.stringify(plans.map((p) => p.attributes)) + hass.language;
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

    const plan = cfg.view === "plan" ? this._plans(tabs ? current : undefined) : "";
    const body = plan || (stations.length ? stations.map((st) => this._station(st)).join("")
      : `<div class="empty">${this._esc(this._t("noStations"))}</div>`);

    this.shadowRoot.innerHTML = `
      <style>${ChargeGateCard.styles}</style>
      <ha-card>
        <div class="head">
          <div class="title">${this._esc(cfg.title || this._t("title"))}</div>
          <div class="summary">${this._esc(this._t("charging_now", { n: charging }))}${done ? " · " + this._esc(this._t("done_now", { n: done })) : ""} · ${this._kw(totalW)} ${this._t("kw")}</div>
        </div>
        ${tabs ? this._tabs(sites, current, allPoints) : ""}
        ${plan ? body : `<div class="grid" style="grid-template-columns:${cols}">${body}</div>`}
      </ha-card>`;
    this.shadowRoot.querySelectorAll(".tab").forEach((el) => {
      el.addEventListener("click", () => this._selectSite(el.dataset.site === "*" ? null : el.dataset.site));
    });
    this.shadowRoot.querySelectorAll(".cgp [data-station]").forEach((el) => {
      el.addEventListener("click", () => {
        const p = this._pointFor(el.dataset.station, Number(el.dataset.connector));
        if (p) this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: p.entity_id }, bubbles: true, composed: true }));
      });
    });
  }

  // --- site plan (view: plan) -------------------------------------------------------------

  _planStates() {
    return Object.values(this._hass.states).filter((s) => s.attributes && s.attributes.source === "chargegate_plan" && s.attributes.layout);
  }

  _pointFor(station, connector) {
    return Object.values(this._hass.states).find((s) => s.attributes && s.attributes.source === "chargegate"
      && s.attributes.station === station && s.attributes.connector === connector && s.entity_id.startsWith("sensor."));
  }

  _plans(tabSite) {
    const cfg = this._config;
    let plans = this._planStates();
    const wanted = cfg.site !== undefined && cfg.site !== "" ? cfg.site : tabSite;
    if (wanted !== undefined && wanted !== null) plans = plans.filter((p) => (p.attributes.site || "") === wanted);
    else if (cfg.sites) plans = plans.filter((p) => cfg.sites.includes(p.attributes.site));
    if (!plans.length) return `<div class="empty">${this._esc(this._t("plan_missing"))}</div>`;
    plans.sort((a, b) => (!a.attributes.site - !b.attributes.site) || (a.attributes.site || "").localeCompare(b.attributes.site || "", undefined, { numeric: true }));
    const lang = (this._hass.language || "en").slice(0, 2);
    const opts = { t: (k, v) => this._t(k, v), lang, showEmployee: cfg.show_employee, showVehicle: cfg.show_vehicle, showSoc: cfg.show_soc };
    const get = (station, connector) => {
      const p = this._pointFor(station, connector);
      if (!p) return null;
      const a = p.attributes, phase = this._state(p);
      const busy = ChargeGatePlan.BUSY.includes(phase);
      return { phase, station_name: a.station_name, connector_label: a.connector_label,
        employee: busy && a.employee && a.employee !== "–" ? a.employee : null, vehicle: busy ? a.vehicle : null,
        power: phase === "offline" ? 0 : (a.power || 0), soc: busy ? a.soc : null, soc_limit: busy ? a.soc_limit : null };
    };
    return plans.map((p) => `<div class="plan">${plans.length > 1 ? `<div class="plan-site">${this._esc(p.attributes.site || this._t("no_site"))}</div>` : ""}
      <div class="plan-scroll">${ChargeGatePlan.render(p.attributes.layout, get, opts)}</div></div>`).join("");
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
    const car = this._car(a, state, active);
    return `
      <div class="point s-${state}" data-entity="${this._esc(p.entity_id)}">
        <div class="row1">
          ${multi ? (a.connector_label
            ? `<span class="lbl" title="${this._esc(a.connector_label)}">${this._esc(a.connector_label)}</span>`
            : `<span class="num">${a.connector}</span>`) : ""}
          <span class="pill" title="OCPP: ${this._esc(a.status)}">${state === "done" ? "✓ " : ""}${this._esc(this._t(state))}</span>
          <span class="who" title="${this._esc(employee)}">${this._esc(employee)}</span>
          ${car ? "" : this._soc(a, active)}
          ${this._dur(a, state, active)}
        </div>
        <div class="row2">
          <div class="bar"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div>
          <span class="kw">${this._kw(power)} <span class="max">/ ${Math.round(max / 1000)} ${this._t("kw")}</span></span>
        </div>
        ${car}
      </div>`;
  }

  // The car charging here (ChargeGate 1.12+ Vehicles): battery with charge limit, range, full at
  _car(a, state, active) {
    const known = a.vehicle || (a.soc_limit !== null && a.soc_limit !== undefined);
    if (!this._config.show_vehicle || !active || !known) return "";
    const has = (v) => v !== null && v !== undefined;
    const soc = has(a.soc) ? Math.round(a.soc) : null;
    const lang = (this._hass.language || "en").slice(0, 2);
    const parts = [];
    if (soc !== null) {
      const from = this._config.show_soc && has(a.soc_start) && a.soc_start < soc ? `${Math.round(a.soc_start)} → ` : "";
      const limit = has(a.soc_limit) ? `<b style="left:${Math.min(100, a.soc_limit)}%"></b>` : "";
      parts.push(`<span class="batt" title="${this._esc(this._t("soc_title", { soc, limit: has(a.soc_limit) ? a.soc_limit : "–" }))}">
        <i style="width:${Math.max(3, Math.min(100, soc))}%"></i>${limit}</span>`);
      parts.push(`<span class="socv">${from}${soc} %</span>`);
      const more = [];
      if (has(a.soc_limit)) more.push(`<span>${this._esc(this._t("limit", { n: a.soc_limit }))}</span>`);
      if (has(a.range_km)) more.push(`<span>${a.range_km.toLocaleString(lang)} km</span>`);
      if (a.full_at && state === "charging" && Date.parse(a.full_at) > Date.now()) {
        const t = new Date(a.full_at).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
        more.push(`<span class="full">${this._esc(this._t("full_at", { t }))}</span>`);
      }
      if (more.length) parts.push(`<span class="more">${more.join(" · ")}</span>`);
    }
    const name = a.vehicle ? `<span class="car-name" title="${this._esc(a.vehicle)}">
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M5 11l1.5-4.5h11L19 11m-1.5 5a1.5 1.5 0 0 1-1.5-1.5a1.5 1.5 0 0 1 1.5-1.5a1.5 1.5 0 0 1 1.5 1.5a1.5 1.5 0 0 1-1.5 1.5m-11 0A1.5 1.5 0 0 1 5 14.5A1.5 1.5 0 0 1 6.5 13A1.5 1.5 0 0 1 8 14.5A1.5 1.5 0 0 1 6.5 16M18.92 6c-.2-.58-.76-1-1.42-1h-11c-.66 0-1.22.42-1.42 1L3 12v8a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-1h12v1a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-8z"/></svg>
      <span>${this._esc(a.vehicle)}</span></span>` : "";
    if (!name && !parts.length) return "";
    return `<div class="row3">${name}${parts.join("")}</div>`;
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
      .plan + .plan { margin-top: 16px; }
      .plan-scroll { overflow-x: auto; }
      .plan-scroll svg { min-width: 520px; }
      .plan-site { font-weight: 600; color: var(--secondary-text-color); margin: 0 0 6px; }
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
      .row3 { display: flex; align-items: center; gap: 4px 6px; flex-wrap: wrap; font-size: .9em;
              color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
      .car-name { display: inline-flex; align-items: center; gap: 4px; color: var(--primary-text-color);
                  min-width: 0; max-width: 12em; margin-right: 4px; }
      .car-name span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .car-name svg { flex: none; color: var(--secondary-text-color); }
      .batt { position: relative; width: 34px; height: 13px; border: 1.5px solid currentColor; border-radius: 3px;
              padding: 1.5px; box-sizing: border-box; flex: none; margin-right: 3px; }
      .batt::after { content: ""; position: absolute; right: -4px; top: 3px; width: 2px; height: 4px;
                     background: currentColor; border-radius: 0 1px 1px 0; }
      .batt i { display: block; height: 100%; border-radius: 1px; background: var(--cg-c); }
      .batt b { position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px;
                background: var(--primary-text-color); opacity: .75; }
      .socv { color: var(--primary-text-color); font-weight: 600; white-space: nowrap; }
      .more { white-space: nowrap; margin-left: 2px; }
      .full { color: var(--cg-c); font-weight: 600; }
      .row2 { display: flex; align-items: center; gap: 10px; }
      .bar { flex: 1; height: 10px; border-radius: 5px; background: var(--divider-color, rgba(127,127,127,.2)); overflow: hidden; }
      .fill { height: 100%; border-radius: 5px; background: var(--cg-c); transition: width .6s ease; }
      .kw { font-variant-numeric: tabular-nums; white-space: nowrap; font-size: .9em; color: var(--primary-text-color); min-width: 88px; text-align: right; }
      .max { color: var(--secondary-text-color); }
      .s-done .batt i { background: var(--cg-done); }
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

// --- site plan renderer -----------------------------------------------------------------------
// Shared by the card (view: plan) and ChargeGate's Site plan page. Pure: layout + point lookup -> SVG.
//   ChargeGatePlan.render(layout, getPoint(station, connector) -> state | null, opts) -> "<svg …>"
//   opts: { t(key, vars), lang, showEmployee, showVehicle, showSoc, edit, selected, pointName(item) }
// Layout units: 20 = 1 m; items are centred at x/y and rotated by rot degrees (see plan.py).
const ChargeGatePlan = (() => {
  const BUSY = ["charging", "done", "connected", "paused"];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fit = (text, width, fs) => {
    const max = Math.max(1, Math.floor(width / (fs * 0.52)));
    text = String(text ?? "");
    return text.length > max ? text.slice(0, Math.max(1, max - 1)) + "…" : text;
  };
  const upright = (rot, extra) => {      // keep text readable: never upside down
    const total = (((rot + extra) % 360) + 360) % 360;
    return total > 90 && total < 270 ? extra + 180 : extra;
  };
  const n = (v) => Math.round(v * 10) / 10;

  const CSS = `
    .cgp { width: 100%; height: auto; display: block; user-select: none; -webkit-user-select: none;
           font-family: inherit; }
    .cgp text { fill: var(--cgp-text, var(--primary-text-color, #1d2320)); dominant-baseline: middle; text-anchor: middle; }
    .cgp .m { fill: var(--cgp-muted, var(--secondary-text-color, #6b7570)); }
    .cgp .lbl { font-weight: 700; }
    .cgp-spot { --cgp-c: var(--cgp-muted, var(--secondary-text-color, #8a948e)); }
    .cgp-spot .b { fill: var(--cgp-c); fill-opacity: .14; stroke: var(--cgp-c); stroke-width: 2; }
    .cgp-spot.cgp-none .b { fill-opacity: 0; stroke-dasharray: 6 4; stroke-width: 1.5; stroke-opacity: .7; }
    .cgp .b { pointer-events: all; }     /* the whole area can be clicked, even where it is not filled */
    .cgp-spot .chg { fill: var(--cgp-c); }
    .cgp-spot .chg path { fill: var(--cgp-on, #fff); }
    .cgp-spot .soc-bg { fill: var(--cgp-muted, #8a948e); fill-opacity: .25; }
    .cgp-spot .soc { fill: var(--cgp-c); }
    .cgp-spot .lim { fill: var(--cgp-text, var(--primary-text-color, #1d2320)); opacity: .7; }
    .cgp-free { --cgp-c: var(--cg-free, #43a047); }
    .cgp-charging { --cgp-c: var(--cg-charging, #039be5); }
    .cgp-done { --cgp-c: var(--cg-done, #00897b); }
    .cgp-connected, .cgp-paused, .cgp-reserved { --cgp-c: var(--cg-connected, #ffa000); }
    .cgp-fault, .cgp-unavailable { --cgp-c: var(--cg-fault, #db4437); }
    .cgp-offline, .cgp-unknown { --cgp-c: var(--cg-offline, #9e9e9e); }
    .cgp-charging .b { fill-opacity: .22; }
    .cgp-charging .chg { animation: cgp-pulse 2s ease-in-out infinite; }
    @keyframes cgp-pulse { 50% { opacity: .45; } }
    .cgp-area .b { stroke: none; }
    .cgp-k-building .b { fill: var(--cgp-muted, #6b7570); fill-opacity: .22; }
    .cgp-k-green .b { fill: #66bb6a; fill-opacity: .25; }
    .cgp-k-road .b { fill: var(--cgp-muted, #6b7570); fill-opacity: .09; }
    .cgp-k-road .line { stroke: var(--cgp-muted, #6b7570); stroke-opacity: .35; stroke-width: 2; stroke-dasharray: 14 12; }
    .cgp .click { cursor: pointer; }
    .cgp.edit [data-id] { cursor: move; }
    .cgp .sel { fill: none; stroke: var(--cgp-sel, var(--primary-color, #0f7a52)); stroke-width: 2.5; stroke-dasharray: 5 3; }
    .cgp .hdl { fill: var(--cgp-sel, var(--primary-color, #0f7a52)); stroke: #fff; stroke-width: 1.5; cursor: nwse-resize; }
    .cgp .grid { stroke: var(--cgp-muted, #8a948e); stroke-opacity: .12; stroke-width: 1; }
  `;

  function spot(it, p, o) {
    const phase = !it.station ? "none" : p ? p.phase : "unknown";
    const busy = p && BUSY.includes(phase);
    const w = it.w, h = it.h, S = Math.min(w, h);
    const extra = upright(it.rot || 0, h > w ? -90 : 0);
    const fs = Math.max(6, Math.min(S * 0.2, 12));
    const cw = Math.min(18, w * 0.4), ch = Math.min(11, h * 0.18);
    const shift = it.station ? ch / 2 + 2 : 0;          // content moves away from the charger
    const L = Math.max(w, h) - (it.station && h >= w ? ch + 4 : 0);
    const parts = [];
    let title = it.label || "";
    // charging station at the head of the space (top edge before rotation)
    if (it.station) {
      parts.push(`<g class="chg" transform="translate(0 ${n(-h / 2 + ch / 2 + 3)})"><rect x="${n(-cw / 2)}" y="${n(-ch / 2)}" width="${n(cw)}" height="${n(ch)}" rx="2"/>
        <path transform="scale(${n(ch / 16)})" d="M1 -6 -3.5 1H-.5L-1.5 6 3.5 -1H.5z"/></g>`);
    }
    // content along the long side of the space
    const c = [];
    const lw = L * 0.86;
    const top = -S / 2 + fs * 0.95;
    const label = it.label || "";
    let status = "";
    if (o.edit) {
      status = it.station ? (o.pointName ? o.pointName(it) : it.station) : "";
    } else if (!it.station) {
      status = "";
    } else if (!p) {
      status = o.t("unknown_point");
    } else if (busy && phase === "charging") {
      status = `${(p.power / 1000).toLocaleString(o.lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} kW`;
    } else {
      status = o.t(phase);
    }
    const head = [label, status].filter(Boolean);
    if (head.length) {
      c.push(`<text y="${n(top)}" font-size="${n(fs)}">${label ? `<tspan class="lbl">${esc(fit(label, lw * 0.45, fs))}</tspan>` : ""}${
        status ? `<tspan class="m" dx="${label ? n(fs * 0.4) : 0}">${esc(fit(status, lw - (label ? fit(label, lw * 0.45, fs).length * fs * 0.6 : 0), fs))}</tspan>` : ""}</text>`);
    }
    if (busy && !o.edit) {
      const who = (o.showEmployee !== false && p.employee) || (o.showVehicle !== false && p.vehicle) || "";
      const second = who && o.showVehicle !== false && p.vehicle && p.vehicle !== who ? p.vehicle : "";
      const nameFs = fs * 1.05;
      const hasSoc = o.showSoc !== false && p.soc !== null && p.soc !== undefined;
      const room = S >= fs * (2 + (second ? 1 : 0) + (hasSoc ? 1 : 0)) * 1.15;   // drop the car line if it doesn't fit
      const showSecond = second && room;
      const y1 = -S / 2 + fs * 2.15;
      if (who) c.push(`<text y="${n(y1)}" font-size="${n(nameFs)}">${esc(fit(who, lw, nameFs))}</text>`);
      if (showSecond) c.push(`<text class="m" y="${n(y1 + fs * 1.1)}" font-size="${n(fs * 0.85)}">${esc(fit(second, lw, fs * 0.85))}</text>`);
      if (hasSoc) {
        const bh = Math.max(3, fs * 0.4), by = S / 2 - fs * 0.75, tw = fs * 1.9;
        const bw = Math.min(lw - tw, L * 0.7), bx = -(bw + tw) / 2;
        c.push(`<rect class="soc-bg" x="${n(bx)}" y="${n(by - bh / 2)}" width="${n(bw)}" height="${n(bh)}" rx="${n(bh / 2)}"/>
          <rect class="soc" x="${n(bx)}" y="${n(by - bh / 2)}" width="${n(bw * Math.max(0.03, Math.min(1, p.soc / 100)))}" height="${n(bh)}" rx="${n(bh / 2)}"/>
          ${p.soc_limit ? `<rect class="lim" x="${n(bx + bw * Math.min(1, p.soc_limit / 100) - 1)}" y="${n(by - bh)}" width="2" height="${n(bh * 2)}"/>` : ""}
          <text x="${n(bx + bw + fs * 0.3)}" y="${n(by)}" font-size="${n(fs * 0.8)}" style="text-anchor:start">${Math.round(p.soc)}%</text>`);
      }
    }
    if (p) {
      title = [label, p.station_name + (p.connector_label ? " · " + p.connector_label : ""), o.t(phase),
        busy && o.showEmployee !== false ? p.employee : "", busy && o.showVehicle !== false ? p.vehicle : "",
        busy && phase === "charging" ? status : "", busy && p.soc != null ? `${Math.round(p.soc)} %` : ""].filter(Boolean).join(" · ");
    }
    const sel = o.edit && o.selected === it.id;
    const attrs = o.edit ? `data-id="${esc(it.id)}"` : it.station ? `class="click" data-station="${esc(it.station)}" data-connector="${it.connector || 1}"` : "";
    return `<g class="cgp-spot cgp-${phase}" transform="translate(${n(it.x)} ${n(it.y)}) rotate(${n(it.rot || 0)})"><g ${attrs}>
      <title>${esc(title)}</title>
      <rect class="b" x="${n(-w / 2)}" y="${n(-h / 2)}" width="${n(w)}" height="${n(h)}" rx="4"/>
      ${parts.join("")}
      <g transform="translate(0 ${n(h >= w ? shift : 0)}) rotate(${extra})">${c.join("")}</g></g>
      ${sel ? selection(w, h) : ""}</g>`;
  }

  function area(it, o) {
    const w = it.w, h = it.h, kind = it.kind || "building";
    const extra = upright(it.rot || 0, h > w * 1.6 ? -90 : 0);
    const L = extra % 180 ? h : w, S = extra % 180 ? w : h;
    const fs = Math.max(8, Math.min(S * 0.3, 18));
    const line = kind === "road" ? (w >= h ? `<line class="line" x1="${n(-w / 2 + 10)}" y1="0" x2="${n(w / 2 - 10)}" y2="0"/>`
      : `<line class="line" x1="0" y1="${n(-h / 2 + 10)}" x2="0" y2="${n(h / 2 - 10)}"/>`) : "";
    const sel = o.edit && o.selected === it.id;
    return `<g class="cgp-area cgp-k-${esc(kind)}" transform="translate(${n(it.x)} ${n(it.y)}) rotate(${n(it.rot || 0)})"><g ${o.edit ? `data-id="${esc(it.id)}"` : ""}>
      <rect class="b" x="${n(-w / 2)}" y="${n(-h / 2)}" width="${n(w)}" height="${n(h)}" rx="3"/>${line}
      ${it.label ? `<g transform="rotate(${extra})"><text class="m" font-size="${n(fs)}" ${kind === "road" ? `y="${n(-S / 2 + fs * 0.9)}"` : ""}>${esc(fit(it.label, L * 0.9, fs))}</text></g>` : ""}</g>
      ${sel ? selection(w, h) : ""}</g>`;
  }

  function selection(w, h) {
    return `<rect class="sel" x="${n(-w / 2 - 4)}" y="${n(-h / 2 - 4)}" width="${n(w + 8)}" height="${n(h + 8)}" rx="6" pointer-events="none"/>
      <circle class="hdl" data-handle="resize" cx="${n(w / 2)}" cy="${n(h / 2)}" r="7"/>`;
  }

  function render(layout, getPoint, o) {
    o = { t: (k) => k, lang: "en", ...(o || {}) };
    const W = layout.w || 1000, H = layout.h || 600;
    const items = layout.items || [];
    const grid = o.edit ? (() => {
      const lines = [];
      for (let x = 20; x < W; x += 20) lines.push(`M${x} 0V${H}`);
      for (let y = 20; y < H; y += 20) lines.push(`M0 ${y}H${W}`);
      return `<path class="grid" d="${lines.join("")}"/>`;
    })() : "";
    const areas = items.filter((i) => i.type === "area").map((i) => area(i, o)).join("");
    const spots = items.filter((i) => i.type === "spot")
      .map((i) => spot(i, i.station ? getPoint(i.station, i.connector || 1) : null, o)).join("");
    return `<svg class="cgp${o.edit ? " edit" : ""}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img">
      <style>${CSS}</style>${grid}${areas}${spots}</svg>`;
  }

  return { render, BUSY };
})();
if (typeof window !== "undefined") window.ChargeGatePlan = ChargeGatePlan;

if (!customElements.get("chargegate-card")) {
  customElements.define("chargegate-card", ChargeGateCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "chargegate-card",
    name: "ChargeGate",
    description: "All ChargeGate charging points: state, power, session duration, employee and car.",
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
    const check = (key, def) => `<label class="chk"><input type="checkbox" data-key="${key}" ${(c[key] ?? def) ? "checked" : ""}> ${this._esc(this._t("ed_" + { show_employee: "employee", show_soc: "soc", show_vehicle: "vehicle", show_site_tabs: "tabs" }[key]))}</label>`;
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
        <label>${this._esc(this._t("ed_view"))}<select data-key="view">
          ${opt("", this._t("ed_view_list"), c.view !== "plan")}${opt("plan", this._t("ed_view_plan"), c.view === "plan")}</select></label>
        <label>${this._esc(this._t("ed_title"))}<input type="text" data-key="title" value="${this._esc(c.title || "")}" placeholder="${this._esc(this._t("title"))}"></label>
        <label>${this._esc(this._t("ed_site"))}<select data-key="site">
          ${opt("", this._t("ed_all"), !c.site)}${sites.map((s) => opt(s, s, c.site === s)).join("")}</select></label>
        ${c.site ? "" : check("show_site_tabs", false)}
        ${c.site || !c.show_site_tabs ? "" : `<label>${this._esc(this._t("ed_default"))}<select data-key="default_site">
          ${opt("", this._t("all_sites"), !c.default_site)}${sites.map((s) => opt(s, s, c.default_site === s)).join("")}</select></label>`}
        <label>${this._esc(this._t("ed_columns"))}<input type="number" min="1" max="6" data-key="columns" value="${this._esc(c.columns || "")}" placeholder="${this._esc(this._t("ed_auto"))}"></label>
        ${check("show_employee", true)}
        ${check("show_soc", true)}
        ${check("show_vehicle", true)}
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
