# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Site plan: a simple drawing of the parking spaces and charging points of a site.

One layout per site (and one for stations without a site), drawn on the Site plan page and shown
live there and on the Home Assistant card (view: plan). Layout JSON:

    {"w": 1000, "h": 600, "items": [
      {"id": "s1", "type": "spot", "x": 100, "y": 80, "w": 50, "h": 100, "rot": 0, "label": "P1",
       "station": "KULTIWB-01", "connector": 1},     # without station: parking space without charger
      {"id": "a1", "type": "area", "kind": "building", "x": 400, "y": 300, "w": 300, "h": 120,
       "rot": 0, "label": "Office"}]}

x / y are the centre of an item, units: 20 = 1 m (a parking space is 50 × 100). rot in degrees.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

import core
import vehicles
from db import PlanLayout, Session, Site, Station, utcnow

KINDS = ("building", "green", "road")
MAX_ITEMS = 400
SPOT_W, SPOT_H, GAP = 50, 100, 4


def site_key(site_id: int | None) -> str:
    return f"site-{site_id}" if site_id else "none"


def site_id_of(key: str) -> int | None:
    m = re.fullmatch(r"site-(\d+)", key or "")
    return int(m.group(1)) if m else None


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.replace(microsecond=0).isoformat() + "Z"


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return round(max(lo, min(hi, f)), 1)


def clean(data: dict) -> dict:
    """Validate a layout sent by the editor."""
    if not isinstance(data, dict):
        raise ValueError("layout must be an object")
    w = _num(data.get("w"), 200, 5000, 1000)
    h = _num(data.get("h"), 150, 5000, 600)
    items, ids = [], set()
    for n, it in enumerate((data.get("items") or [])[:MAX_ITEMS]):
        if not isinstance(it, dict) or it.get("type") not in ("spot", "area"):
            continue
        iid = re.sub(r"[^A-Za-z0-9_-]", "", str(it.get("id") or ""))[:20] or f"i{n}"
        while iid in ids:
            iid += "x"
        ids.add(iid)
        out = {"id": iid, "type": it["type"],
               "x": _num(it.get("x"), 0, w, w / 2), "y": _num(it.get("y"), 0, h, h / 2),
               "w": _num(it.get("w"), 10, 3000, SPOT_W), "h": _num(it.get("h"), 10, 3000, SPOT_H),
               "rot": round(_num(it.get("rot"), -1e6, 1e6, 0) % 360, 1),
               "label": str(it.get("label") or "").strip()[:30]}
        if it["type"] == "spot":
            station = str(it.get("station") or "").strip()[:64]
            if station:
                out["station"] = station
                out["connector"] = int(_num(it.get("connector"), 1, 99, 1))
        else:
            out["kind"] = it.get("kind") if it.get("kind") in KINDS else "building"
        items.append(out)
    return {"w": w, "h": h, "items": items}


async def load(key: str) -> dict | None:
    async with Session() as s:
        row = await s.get(PlanLayout, key)
    return json.loads(row.data) if row else None


async def save(key: str, data: dict) -> dict:
    layout = clean(data)
    async with Session() as s:
        row = await s.get(PlanLayout, key)
        text = json.dumps(layout, ensure_ascii=False, separators=(",", ":"))
        if row:
            row.data, row.updated = text, utcnow()
        else:
            s.add(PlanLayout(key=key, data=text))
        await s.commit()
    core.notify_all()
    return layout


async def delete(key: str) -> None:
    async with Session() as s:
        if row := await s.get(PlanLayout, key):
            await s.delete(row)
            await s.commit()
    core.notify_all()


async def all_layouts() -> list[tuple[str, str, dict, datetime]]:
    """[(key, site name or "", layout, updated)] – for Home Assistant."""
    async with Session() as s:
        rows = (await s.execute(select(PlanLayout))).scalars().all()
        names = {site_key(x.id): x.name for x in (await s.execute(select(Site))).scalars()}
    return [(r.key, names.get(r.key, ""), json.loads(r.data), r.updated) for r in rows
            if r.key == "none" or r.key in names]


async def charging_points() -> list[dict]:
    """All charging points of approved stations: [{station, connector, name, site_key, site}]."""
    async with Session() as s:
        stations = (await s.execute(select(Station).where(Station.approved).options(
            selectinload(Station.connectors), selectinload(Station.site)))).scalars().all()
    out = []
    for st in sorted(stations, key=lambda x: (x.name or x.id).casefold()):
        conns = sorted(c.connector_id for c in st.connectors if c.connector_id > 0) or [1]
        for c in conns:
            name = st.name or st.id
            if len(conns) > 1 or (st.connector_names or "").strip():
                name += " · " + st.connector_label(c)
            out.append({"station": st.id, "connector": c, "name": name,
                        "site_key": site_key(st.site_id), "site": st.site.name if st.site else ""})
    return out


async def sites() -> list[dict]:
    """Sites that have approved stations or a layout: [{key, name}] – sites by name, "no site" last."""
    async with Session() as s:
        site_rows = (await s.execute(select(Site))).scalars().all()
        keys = set((await s.execute(select(PlanLayout.key))).scalars())
    used = {p["site_key"] for p in await charging_points()} | keys
    out = [{"key": site_key(x.id), "name": x.name} for x in site_rows if site_key(x.id) in used]
    out.sort(key=lambda x: x["name"].casefold())
    if "none" in used:
        out.append({"key": "none", "name": ""})
    return out


def suggest(points: list[dict]) -> dict:
    """First layout of a site: one row of parking spaces, one per charging point."""
    n = max(1, len(points))
    w = max(600, 60 + n * (SPOT_W + GAP))
    items = []
    for i, p in enumerate(points or [None]):
        it = {"id": f"s{i + 1}", "type": "spot", "x": 40 + SPOT_W / 2 + i * (SPOT_W + GAP), "y": 40 + SPOT_H / 2,
              "w": SPOT_W, "h": SPOT_H, "rot": 0, "label": f"P{i + 1}"}
        if p:
            it.update(station=p["station"], connector=p["connector"])
        items.append(it)
    items.append({"id": "a1", "type": "area", "kind": "road", "x": w / 2, "y": 40 + SPOT_H + 60,
                  "w": w - 40, "h": 100, "rot": 0, "label": ""})
    return clean({"w": w, "h": SPOT_H + 220, "items": items})


async def live() -> dict[str, dict]:
    """Current state of every charging point: {"station:connector": {...}} – for the Site plan page."""
    async with Session() as s:
        stations = (await s.execute(select(Station).where(Station.approved)
                                    .options(selectinload(Station.connectors)))).scalars().all()
    active = await core.active_sessions()
    out = {}
    for st in stations:
        online = st.id in core.connected
        conns = [c for c in st.connectors if c.connector_id > 0]
        for cs in conns:
            tx = active.get((st.id, cs.connector_id))
            car = tx.vehicle if tx is not None else None
            busy = tx is not None and online
            out[f"{st.id}:{cs.connector_id}"] = {
                "phase": core.session_phase(cs, tx, online),
                "station_name": st.name or st.id,
                "connector_label": st.connector_label(cs.connector_id) if (st.connector_names or "").strip() else None,
                "employee": ((tx.employee.name if tx.employee else tx.tag_uid) if busy else None),
                "vehicle": car.label if busy and car is not None else None,
                "power": round(cs.power_w or 0) if busy else 0,
                "max_power": cs.max_power_w,
                "soc": round(cs.soc) if busy and cs.soc is not None else None,
                "soc_start": round(tx.soc_start) if busy and tx.soc_start is not None else None,
                "soc_limit": round(car.limit_soc) if busy and car is not None and car.limit_soc is not None else None,
                "full_at": iso(vehicles.full_at(car)) if busy and car is not None else None,
                "session_start": iso(tx.started_at) if busy else None,
            }
    return out
