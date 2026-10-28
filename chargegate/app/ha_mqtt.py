# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Publish stations and sessions to Home Assistant via MQTT discovery.

Every approved station becomes a Home Assistant device with entities per connector:
status, charging, power (W), energy register (kWh, usable in the Energy dashboard),
session energy and – depending on HA_EMPLOYEE_DISPLAY – the employee currently charging.
All topics are retained, so Home Assistant restarts are no problem.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

import aiomqtt
from sqlalchemy import select
from sqlalchemy.orm import selectinload

import config
import core
from db import Session, Station

log = logging.getLogger("chargegate.mqtt")

BASE = config.MQTT_BASE_TOPIC
PREFIX = config.MQTT_DISCOVERY_PREFIX
AVAILABILITY = f"{BASE}/status"
HUB_ID = "chargegate_hub"

_NAMES = {
    "en": {"online": "Online", "status": "Status", "charging": "Charging", "power": "Power",
           "energy": "Energy", "session_energy": "Session energy", "employee": "Employee",
           "connector": "Connector {c}", "soc": "Battery", "state": "State", "running": "Running sessions", "stations_online": "Stations online"},
    "de": {"online": "Online", "status": "Status", "charging": "Lädt", "power": "Leistung",
           "energy": "Energie", "session_energy": "Energie Ladevorgang", "employee": "Mitarbeiter",
           "connector": "Anschluss {c}", "soc": "Akkustand", "state": "Zustand", "running": "Laufende Ladevorgänge", "stations_online": "Stationen online"},
}
NAMES = _NAMES["de" if config.LANGUAGE == "de" else "en"]
_PHASES = {
    "en": {"offline": "Offline", "free": "Free", "connected": "Connected", "charging": "Charging",
           "done": "Done", "paused": "Paused", "fault": "Fault", "unavailable": "Unavailable",
           "reserved": "Reserved"},
    "de": {"offline": "Offline", "free": "Frei", "connected": "Verbunden", "charging": "Lädt",
           "done": "Fertig", "paused": "Pausiert", "fault": "Störung", "unavailable": "Nicht verfügbar",
           "reserved": "Reserviert"},
}
PHASES = _PHASES["de" if config.LANGUAGE == "de" else "en"]
BUSY_PHASES = {"charging", "done", "paused", "connected"}


def iso(dt) -> str | None:
    return None if dt is None else dt.replace(microsecond=0).isoformat() + "Z"
ORIGIN = {"name": "ChargeGate", "sw_version": config.VERSION,
          "support_url": "https://github.com/kultikom/chargegate"}


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def employee_label(name: str | None) -> str:
    if not name:
        return "–"
    if config.HA_EMPLOYEE_DISPLAY == "initials":
        return "".join(p[0].upper() + "." for p in name.split() if p) or "–"
    return name


class Bridge:
    def __init__(self) -> None:
        self._pending: set[str | None] = {None}       # None = resync everything
        self._event = asyncio.Event()
        self._client: aiomqtt.Client | None = None
        self._sent: dict[str, str] = {}               # topic -> last payload (discovery only)
        self._known: dict[str, set[int]] = {}         # station -> connectors with entities
        self._has_sessions = False

    # called by core.notify() – must not block
    def listener(self, station_id: str | None) -> None:
        self._pending.add(station_id)
        self._event.set()

    async def run(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(
                        hostname=config.MQTT_HOST, port=config.MQTT_PORT,
                        username=config.MQTT_USERNAME or None, password=config.MQTT_PASSWORD or None,
                        identifier="chargegate",
                        will=aiomqtt.Will(AVAILABILITY, "offline", qos=1, retain=True)) as client:
                    self._client, self._sent = client, {}
                    log.info("Connected to MQTT broker %s:%s", config.MQTT_HOST, config.MQTT_PORT)
                    await self._pub(AVAILABILITY, "online")
                    self._pending.add(None)
                    self._event.set()
                    while True:
                        try:
                            # also wake up every minute: "done" depends on elapsed time
                            await asyncio.wait_for(self._event.wait(), timeout=60)
                        except TimeoutError:
                            if not self._has_sessions:
                                continue
                            self._pending.add(None)
                        self._event.clear()
                        await asyncio.sleep(0.5)         # batch bursts of updates
                        pending, self._pending = self._pending, set()
                        await self._process(pending)
            except asyncio.CancelledError:
                raise
            except aiomqtt.MqttError as exc:
                log.warning("MQTT connection lost (%s) – retrying in 15 s", exc)
            except Exception:  # noqa: BLE001
                log.exception("MQTT bridge error – retrying in 15 s")
            self._client = None
            await asyncio.sleep(15)

    # --- publishing ------------------------------------------------------------------------

    async def _pub(self, topic: str, payload: str, retain: bool = True) -> None:
        await self._client.publish(topic, payload, qos=1, retain=retain)

    async def _config(self, component: str, node: str, obj: str, payload: dict | None) -> None:
        """Publish a discovery config, only if it changed. None removes the entity."""
        topic = f"{PREFIX}/{component}/{node}/{obj}/config"
        text = "" if payload is None else json.dumps(payload, ensure_ascii=False)
        if self._sent.get(topic) == text:
            return
        self._sent[topic] = text
        await self._pub(topic, text)

    async def _process(self, pending: set[str | None]) -> None:
        async with Session() as s:
            if None in pending:
                ids = set((await s.execute(select(Station.id))).scalars()) | set(self._known)
            else:
                ids = {p for p in pending if p}
        for sid in ids:
            await self._sync_station(sid)
        await self._sync_hub()

    async def _sync_hub(self) -> None:
        device = {"identifiers": [HUB_ID], "name": "ChargeGate", "manufacturer": "KULTIKOM",
                  "model": "ChargeGate", "sw_version": config.VERSION}
        common = {"device": device, "origin": ORIGIN, "availability_topic": AVAILABILITY,
                  "state_topic": f"{BASE}/hub/state"}
        await self._config("sensor", "chargegate", "running_sessions", {
            **common, "name": NAMES["running"], "unique_id": "chargegate_running_sessions",
            "value_template": "{{ value_json.running }}", "state_class": "measurement",
            "icon": "mdi:ev-station"})
        await self._config("sensor", "chargegate", "stations_online", {
            **common, "name": NAMES["stations_online"], "unique_id": "chargegate_stations_online",
            "value_template": "{{ value_json.online }}", "state_class": "measurement",
            "icon": "mdi:lan-connect"})
        running = len(await core.active_sessions())
        await self._pub(f"{BASE}/hub/state", json.dumps({"running": running, "online": len(core.connected)}))
        self._has_sessions = running > 0

    async def _sync_station(self, sid: str) -> None:
        node = f"cg_{slug(sid)}"
        async with Session() as s:
            st = (await s.execute(select(Station).where(Station.id == sid).options(
                selectinload(Station.site), selectinload(Station.connectors)))).scalar_one_or_none()
        active = {} if st is None else await core.active_sessions([sid])

        if st is None or not st.approved:
            await self._remove_station(sid, node)
            return

        connectors = [c for c in st.connectors if c.connector_id > 0]
        counts_energy = st.site.counts_energy if st.site else config.HA_ENERGY_NO_SITE
        multi = len(connectors) > 1
        device = {"identifiers": [f"chargegate_{slug(sid)}"], "name": st.name or st.id,
                  "manufacturer": st.vendor or None, "model": st.model or None,
                  "sw_version": st.firmware or None, "serial_number": st.serial or None,
                  "via_device": HUB_ID}
        if st.site:
            device["suggested_area"] = st.site.name
        device = {k: v for k, v in device.items() if v is not None}
        station_topic = f"{BASE}/{slug(sid)}"
        avail = [{"topic": AVAILABILITY}, {"topic": f"{station_topic}/online",
                                           "payload_available": "ON", "payload_not_available": "OFF"}]

        await self._config("binary_sensor", node, "online", {
            "name": NAMES["online"], "unique_id": f"chargegate_{slug(sid)}_online", "device": device,
            "origin": ORIGIN, "availability_topic": AVAILABILITY, "state_topic": f"{station_topic}/online",
            "device_class": "connectivity", "entity_category": "diagnostic"})
        await self._pub(f"{station_topic}/online", "ON" if sid in core.connected else "OFF")

        tx_by_connector = {c: t for (_sid, c), t in active.items()}
        for cs in connectors:
            c = cs.connector_id
            prefix = NAMES["connector"].format(c=c) + " " if multi else ""
            uid = f"chargegate_{slug(sid)}_{c}"
            state_topic = f"{station_topic}/{c}/state"
            common = {"device": device, "origin": ORIGIN, "availability": avail,
                      "availability_mode": "all", "state_topic": state_topic}

            def name(key: str) -> str:
                return (prefix + NAMES[key]).strip() if multi else NAMES[key]

            # The status sensor stays available while the station is offline and carries the
            # whole connector state as attributes – the ChargeGate dashboard card reads these.
            await self._config("sensor", node, f"{c}_status", {
                **common, "availability": [{"topic": AVAILABILITY}], "availability_mode": "all",
                "name": name("status"), "unique_id": f"{uid}_status",
                "value_template": "{{ value_json.status if value_json.online else 'Offline' }}",
                "json_attributes_topic": state_topic, "icon": "mdi:ev-plug-type2"})
            await self._config("sensor", node, f"{c}_state", {
                **common, "availability": [{"topic": AVAILABILITY}], "availability_mode": "all",
                "name": name("state"), "unique_id": f"{uid}_state",
                "value_template": "{{ value_json.phase_label }}",
                "json_attributes_topic": state_topic,
                "json_attributes_template": "{{ {'phase': value_json.phase, 'idle_since': value_json.idle_since} | tojson }}",
                "icon": "mdi:ev-station"})
            await self._config("binary_sensor", node, f"{c}_charging", {
                **common, "name": name("charging"), "unique_id": f"{uid}_charging",
                "value_template": "{{ 'ON' if value_json.charging else 'OFF' }}",
                "device_class": "battery_charging"})
            await self._config("sensor", node, f"{c}_power", {
                **common, "name": name("power"), "unique_id": f"{uid}_power",
                "value_template": "{{ value_json.power }}", "unit_of_measurement": "W",
                "device_class": "power", "state_class": "measurement"})
            # Only stations of sites "counting" here are energy meters for HA's Energy dashboard.
            # Others still show their kWh, but without device_class/state_class they can't be
            # picked there and don't create long-term energy statistics.
            meter = ({"device_class": "energy", "state_class": "total_increasing"} if counts_energy
                     else {"icon": "mdi:lightning-bolt-outline"})
            await self._config("sensor", node, f"{c}_energy", {
                **common, "name": name("energy"), "unique_id": f"{uid}_energy",
                "value_template": "{{ value_json.energy }}", "unit_of_measurement": "kWh",
                **meter, "suggested_display_precision": 2})
            await self._config("sensor", node, f"{c}_session_energy", {
                **common, "name": name("session_energy"), "unique_id": f"{uid}_session_energy",
                "value_template": "{{ value_json.session_energy }}", "unit_of_measurement": "kWh",
                **meter, "suggested_display_precision": 2})
            show_employee = config.HA_EMPLOYEE_DISPLAY != "hidden"
            await self._config("sensor", node, f"{c}_employee", {
                **common, "name": name("employee"), "unique_id": f"{uid}_employee",
                "value_template": "{{ value_json.employee }}", "icon": "mdi:account"}
                if show_employee else None)
            # battery level only exists if the station has ever reported it (DC / ISO 15118)
            await self._config("sensor", node, f"{c}_soc", {
                **common, "name": name("soc"), "unique_id": f"{uid}_soc",
                "value_template": "{{ value_json.soc if value_json.soc is not none else 'unknown' }}",
                "unit_of_measurement": "%", "device_class": "battery", "state_class": "measurement"}
                if cs.soc_supported else None)

            tx = tx_by_connector.get(c)
            online = sid in core.connected
            phase = core.session_phase(cs, tx, online)
            state = {
                "phase": phase,
                "phase_label": PHASES[phase],
                "idle_since": iso(cs.idle_since) if tx is not None and online else None,
                "source": "chargegate",
                "station": sid,
                "station_name": st.name or st.id,
                "site": st.site.name if st.site else None,
                "connector": c,
                "connector_label": st.connector_label(c) if (st.connector_names or "").strip() else None,
                "connectors": len(connectors),
                "online": online,
                "status": cs.status,
                "charging": tx is not None,
                "power": round(cs.power_w or 0) if tx is not None and online else 0,
                "max_power": cs.max_power_w,
                "energy": round(cs.energy_wh / 1000, 3) if cs.energy_wh is not None else None,
                "session_energy": (tx.energy_kwh or 0) if tx is not None else 0,
                "session_start": iso(tx.started_at) if tx is not None else None,
                "soc": round(cs.soc) if cs.soc is not None and online else None,
                "soc_start": round(tx.soc_start) if tx is not None and tx.soc_start is not None else None,
            }
            if tx is None and phase in BUSY_PHASES:
                # Session start not received yet (stuck in the station's queue): the station is
                # busy anyway – show it as such, with whoever just presented a tag here
                state["charging"] = True
            if show_employee:
                who = (tx.employee.name if tx.employee else tx.tag_uid) if tx else None
                if tx is None and phase in BUSY_PHASES:
                    who = await core.pending_authorization(sid, c, len(connectors) == 1)
                state["employee"] = employee_label(who)
            await self._pub(state_topic, json.dumps(state, ensure_ascii=False))
        self._known[sid] = {c.connector_id for c in connectors}

    async def _remove_station(self, sid: str, node: str) -> None:
        connectors = self._known.pop(sid, None)
        if connectors is None:
            return
        await self._config("binary_sensor", node, "online", None)
        await self._pub(f"{BASE}/{slug(sid)}/online", "")          # clear retained states
        for c in connectors:
            await self._pub(f"{BASE}/{slug(sid)}/{c}/state", "")
        for c in connectors:
            for comp, obj in (("sensor", "status"), ("binary_sensor", "charging"), ("sensor", "power"),
                              ("sensor", "energy"), ("sensor", "session_energy"), ("sensor", "employee"),
                              ("sensor", "soc"), ("sensor", "state")):
                await self._config(comp, node, f"{c}_{obj}", None)
        log.info("Removed %s from Home Assistant", sid)


bridge: Bridge | None = None
_task: asyncio.Task | None = None


def start() -> bool:
    """Create the bridge and start it in the background (if MQTT is configured)."""
    global bridge, _task
    if not (config.MQTT_ENABLED and config.MQTT_HOST):
        return False
    bridge = Bridge()
    core.add_listener(bridge.listener)
    _task = asyncio.create_task(bridge.run())
    return True
