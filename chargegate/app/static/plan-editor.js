// SPDX-License-Identifier: BUSL-1.1
// Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
// Site plan page: live view and editor. Drawing is done by ChargeGatePlan (chargegate-card.js).
(() => {
  const C = window.CG_PLAN;
  const $ = (id) => document.getElementById(id);
  const t = (k, v) => { let s = C.t[k] || k; for (const [a, b] of Object.entries(v || {})) s = s.replace(`{${a}}`, b); return s; };
  const SNAP = 5;
  const snap = (v) => Math.round(v / SNAP) * SNAP;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const timeOf = (iso) => new Date(iso).toLocaleTimeString(C.lang, { hour: "2-digit", minute: "2-digit" });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let saved = C.layout;            // what is stored
  let live = {};                   // "station:connector" -> state
  let layout = null;               // being edited
  let selected = null, dirty = false, drag = null, frame = 0;

  const pointKey = (it) => `${it.station}:${it.connector || 1}`;
  const pointName = (it) => {
    const p = C.points.find((x) => x.station === it.station && x.connector === (it.connector || 1));
    return p ? p.name : it.station;
  };

  // --- live view ------------------------------------------------------------------------------

  function renderView() {
    const box = $("plan");
    if (!saved) {
      box.innerHTML = `<div class="empty" style="padding:28px 12px">${esc(t("empty"))}</div>`;
      return;
    }
    box.innerHTML = ChargeGatePlan.render(saved, (s, c) => live[`${s}:${c}`] || null,
      { t, lang: C.lang, showEmployee: true, showVehicle: true, showSoc: true });
    box.querySelectorAll("[data-station]").forEach((el) => el.addEventListener("click", () => info(el.dataset.station, Number(el.dataset.connector))));
  }

  function info(station, connector) {
    const p = live[`${station}:${connector}`], box = $("plan-info");
    if (!p) { box.hidden = true; return; }
    const busy = ChargeGatePlan.BUSY.includes(p.phase);
    const parts = [`<b>${esc(p.station_name)}${p.connector_label ? " · " + esc(p.connector_label) : ""}</b>`, esc(t(p.phase))];
    if (busy) {
      if (p.employee) parts.push(esc(p.employee));
      if (p.vehicle) parts.push(esc(p.vehicle));
      if (p.phase === "charging") parts.push(`${(p.power / 1000).toLocaleString(C.lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} kW`);
      if (p.soc != null) parts.push((p.soc_start != null && p.soc_start < p.soc ? `${p.soc_start} → ` : "") + `${p.soc} %` + (p.soc_limit ? ` / ${p.soc_limit} %` : ""));
      if (p.full_at && p.phase === "charging") parts.push(esc(t("full_at", { time: timeOf(p.full_at) })));
      if (p.session_start) parts.push(esc(t("since", { time: timeOf(p.session_start) })));
    }
    box.innerHTML = parts.join(" · ");
    box.hidden = false;
  }

  async function refresh() {
    if (layout) return;                       // editing
    try {
      const r = await fetch(`${C.base}/plan/data?site=${encodeURIComponent(C.key)}`, { credentials: "same-origin" });
      if (!r.ok) return;
      const d = await r.json();
      live = d.points || {};
      saved = d.layout;
      renderView();
      $("plan-status").textContent = saved ? t("updated", { time: new Date().toLocaleTimeString(C.lang) }) : "";
    } catch (e) { /* offline – try again */ }
  }

  // --- editor -----------------------------------------------------------------------------

  function startEdit() {
    layout = clone(saved || C.suggestion);
    dirty = !saved;
    selected = null;
    $("plan-view").hidden = true;
    $("plan-editor").hidden = false;
    $("c-w").value = layout.w; $("c-h").value = layout.h;
    renderEdit();
    props();
  }

  function stopEdit() {
    layout = null; selected = null; dirty = false;
    $("plan-editor").hidden = true;
    $("plan-view").hidden = false;
    refresh();
  }

  function renderEdit() {
    $("plan-edit-canvas").innerHTML = ChargeGatePlan.render(layout, () => null,
      { t, lang: C.lang, edit: true, selected, pointName });
    $("plan-edit-canvas").querySelector("svg").style.background = "var(--bg)";
  }

  function rerender() {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; renderEdit(); });
  }

  const item = (id = selected) => layout && layout.items.find((i) => i.id === id);
  const newId = (p) => { let n = 1; while (layout.items.some((i) => i.id === p + n)) n++; return p + n; };
  const nextLabel = () => {
    const nums = layout.items.map((i) => /^P(\d+)$/.exec(i.label || "")).filter(Boolean).map((m) => Number(m[1]));
    return "P" + ((nums.length ? Math.max(...nums) : 0) + 1);
  };
  function changed() { dirty = true; rerender(); props(); }

  function freePlace(w, h) {               // right of the last spot, or the centre
    const spots = layout.items.filter((i) => i.type === "spot");
    const last = spots[spots.length - 1];
    if (last && last.x + last.w * 1.5 + 4 < layout.w) return { x: snap(last.x + last.w + 4), y: last.y };
    return { x: snap(layout.w / 2), y: snap(Math.min(layout.h - h / 2, layout.h / 2)) };
  }

  function add(act) {
    if (act === "spot" || act === "row") {
      const count = act === "row" ? Math.max(2, Math.min(40, Number($("row-count").value) || 5)) : 1;
      const at = freePlace(50, 100);
      let first = null;
      for (let i = 0; i < count; i++) {
        const it = { id: newId("s"), type: "spot", x: at.x + i * 54, y: at.y, w: 50, h: 100, rot: 0, label: nextLabel() };
        if (it.x + 25 > layout.w) layout.w = snap(it.x + 45);
        layout.items.push(it);
        first = first || it;
      }
      selected = first.id;
    } else {
      const size = { building: [240, 140], road: [Math.max(200, layout.w - 80), 100], green: [200, 60] }[act];
      const it = { id: newId("a"), type: "area", kind: act, x: snap(layout.w / 2), y: snap(layout.h / 2), w: size[0], h: size[1], rot: 0, label: "" };
      layout.items.push(it);                // drawn on top of the other areas, below the parking spaces
      selected = it.id;
    }
    $("c-w").value = layout.w;
    changed();
  }

  function act(a) {
    if (["spot", "row", "building", "road", "green"].includes(a)) return add(a);
    const it = item();
    if (!it) return;
    if (a === "rot90" || a === "rot15") it.rot = ((it.rot || 0) + (a === "rot90" ? 90 : 15)) % 360;
    if (a === "del") { layout.items = layout.items.filter((i) => i !== it); selected = null; }
    if (a === "back") {                     // to the back of its kind (areas always stay below spaces)
      layout.items = layout.items.filter((i) => i !== it);
      layout.items.unshift(it);             // areas are drawn in list order (spaces always on top)
    }
    if (a === "dup") {
      const copy = { ...clone(it), id: newId(it.type === "spot" ? "s" : "a") };
      const step = it.rot % 180 === 90 ? { x: 0, y: it.w + 4 } : { x: it.w + 4, y: 0 };
      copy.x = Math.min(layout.w, it.x + step.x); copy.y = Math.min(layout.h, it.y + step.y);
      if (copy.type === "spot") { copy.label = nextLabel(); delete copy.station; delete copy.connector; }
      layout.items.push(copy);
      selected = copy.id;
    }
    changed();
  }

  // properties panel
  function props() {
    const it = item();
    $("props-empty").style.display = it ? "none" : "";
    $("props").hidden = false;
    $("props").style.display = it ? "grid" : "none";
    if (!it) return;
    $("p-label").value = it.label || "";
    $("p-w").value = it.w; $("p-h").value = it.h; $("p-rot").value = it.rot || 0;
    $("p-point-wrap").style.display = it.type === "spot" ? "" : "none";
    $("p-kind-wrap").style.display = it.type === "area" ? "" : "none";
    if (it.type === "area") $("p-kind").value = it.kind || "building";
    if (it.type === "spot") {
      const used = new Set(layout.items.filter((i) => i.type === "spot" && i.station && i !== it).map(pointKey));
      const opt = (p) => `<option value="${esc(p.station)}:${p.connector}">${esc(p.name)}${used.has(`${p.station}:${p.connector}`) ? " (" + esc(t("used")) + ")" : ""}</option>`;
      const here = C.points.filter((p) => p.site_key === C.key), other = C.points.filter((p) => p.site_key !== C.key);
      let html = `<option value="">${esc(t("no_point"))}</option>` + here.map(opt).join("");
      if (other.length) html += `<optgroup label="${esc(t("other_sites"))}">${other.map(opt).join("")}</optgroup>`;
      if (it.station && !C.points.some((p) => p.station === it.station && p.connector === (it.connector || 1))) {
        html += `<option value="${esc(pointKey(it))}">${esc(it.station)} (${esc(t("unknown_point"))})</option>`;
      }
      $("p-point").innerHTML = html;
      $("p-point").value = it.station ? pointKey(it) : "";
    }
  }

  function onProp(e) {
    const it = item();
    if (!it) return;
    const id = e.target.id;
    if (id === "p-label") it.label = e.target.value.slice(0, 30);
    if (id === "p-w") it.w = Math.max(10, Number(e.target.value) || it.w);
    if (id === "p-h") it.h = Math.max(10, Number(e.target.value) || it.h);
    if (id === "p-rot") it.rot = (((Number(e.target.value) || 0) % 360) + 360) % 360;
    if (id === "p-kind") it.kind = e.target.value;
    if (id === "p-point") {
      const v = e.target.value;
      if (!v) { delete it.station; delete it.connector; } else {
        const i = v.lastIndexOf(":");
        it.station = v.slice(0, i); it.connector = Number(v.slice(i + 1)) || 1;
      }
    }
    dirty = true;
    rerender();
  }

  // pointer: select, move, resize
  function svgPoint(e) {
    const svg = $("plan-edit-canvas").querySelector("svg");
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }

  function onDown(e) {
    if (!layout || e.button > 0) return;
    const handle = e.target.closest("[data-handle]");
    const g = e.target.closest("[data-id]");
    const p = svgPoint(e);
    if (handle && item()) {
      const it = item();
      drag = { mode: "resize", it, p0: p, w0: it.w, h0: it.h, x0: it.x, y0: it.y };
    } else if (g) {
      selected = g.dataset.id;
      const it = item();
      drag = { mode: "move", it, p0: p, x0: it.x, y0: it.y };
      props();
    } else {
      selected = null;
      props();
    }
    rerender();
    e.preventDefault();
  }

  function onMove(e) {
    if (!drag) return;
    const p = svgPoint(e), it = drag.it;
    const dx = p.x - drag.p0.x, dy = p.y - drag.p0.y;
    if (drag.mode === "move") {
      it.x = Math.max(0, Math.min(layout.w, snap(drag.x0 + dx)));
      it.y = Math.max(0, Math.min(layout.h, snap(drag.y0 + dy)));
    } else {
      const r = (it.rot || 0) * Math.PI / 180, cos = Math.cos(r), sin = Math.sin(r);
      const lx = dx * cos + dy * sin, ly = -dx * sin + dy * cos;     // delta in the item's own frame
      const w = Math.max(10, snap(drag.w0 + lx)), h = Math.max(10, snap(drag.h0 + ly));
      const ex = (w - drag.w0) / 2, ey = (h - drag.h0) / 2;           // keep the opposite corner in place
      it.w = w; it.h = h;
      it.x = drag.x0 + ex * cos - ey * sin;
      it.y = drag.y0 + ex * sin + ey * cos;
    }
    dirty = true;
    rerender();
  }

  function onUp() {
    if (drag) { drag = null; props(); }
  }

  function onKey(e) {
    if (!layout || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    const it = item();
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") { e.preventDefault(); act("dup"); return; }
    if (!it) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); act("del"); }
    else if (e.key.toLowerCase() === "r") act(e.shiftKey ? "rot15" : "rot90");
    else if (e.key.startsWith("Arrow")) {
      const step = e.shiftKey ? 20 : SNAP;
      if (e.key === "ArrowLeft") it.x -= step;
      if (e.key === "ArrowRight") it.x += step;
      if (e.key === "ArrowUp") it.y -= step;
      if (e.key === "ArrowDown") it.y += step;
      e.preventDefault();
      changed();
    }
  }

  async function save() {
    layout.w = Math.max(200, Number($("c-w").value) || layout.w);
    layout.h = Math.max(150, Number($("c-h").value) || layout.h);
    const btn = $("btn-save");
    btn.disabled = true;
    try {
      const r = await fetch(`${C.base}/plan/${encodeURIComponent(C.key)}`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(layout) });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || r.status);
      saved = d.layout;
      $("btn-edit").textContent = t("edit");
      stopEdit();
      $("plan-status").textContent = t("saved");
    } catch (err) {
      alert(t("save_failed") + ": " + err.message);
    } finally {
      btn.disabled = false;
    }
  }

  // --- wiring ---------------------------------------------------------------------------------

  $("btn-edit").addEventListener("click", startEdit);
  $("btn-cancel").addEventListener("click", () => { if (!dirty || confirm(t("unsaved"))) stopEdit(); });
  $("btn-save").addEventListener("click", save);
  document.querySelectorAll("#plan-editor [data-act]").forEach((b) => b.addEventListener("click", () => act(b.dataset.act)));
  ["p-label", "p-w", "p-h", "p-rot", "p-kind", "p-point"].forEach((id) => $(id).addEventListener("input", onProp));
  ["c-w", "c-h"].forEach((id) => $(id).addEventListener("change", () => {
    layout.w = Math.max(200, Number($("c-w").value) || layout.w);
    layout.h = Math.max(150, Number($("c-h").value) || layout.h);
    changed();
  }));
  $("plan-edit-canvas").addEventListener("pointerdown", onDown);
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("keydown", onKey);
  window.addEventListener("beforeunload", (e) => { if (layout && dirty) { e.preventDefault(); e.returnValue = ""; } });

  renderView();
  refresh();
  setInterval(refresh, 5000);
  if (!saved && new URLSearchParams(location.search).has("edit")) startEdit();
})();
