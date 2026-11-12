# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Vehicles: battery level from a vehicle data source, cars assigned to employees and to sessions.

AC charging (Type 2, IEC 61851) doesn't tell the station the car's battery level. ChargeGate takes
it from a vehicle data source – first source: TeslaMate via MQTT – and is the one place where cars
are assigned to employees (Vehicles page). For a running session it records the battery level
(soc_start / soc_last, like stations that report it themselves), shows it in the UI and Home
Assistant and sends it to stations with a display (KultiWB, OCPP DataTransfer "VehicleInfo").

Which car is charging in a session:
1. the employee's car – with several cars the one that is plugged in
2. otherwise the car that reported "plugged in" within 5 minutes of the session start, if exactly one
3. or set by hand on the Vehicles page (two cars plugged in at the same moment, pool cars)
A car already charging in another session is never picked twice. If no car matches at the start,
the session is matched again as soon as a car reports being plugged in.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiomqtt
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

import config
import core
import licensing
from db import ConnectorStatus, Session, Transaction, Vehicle, running_clause, utcnow

log = logging.getLogger("chargegate.vehicles")

SOURCES = ("off", "teslamate")
DEFAULT_TOPIC = "teslamate"
PLUG_WINDOW = timedelta(minutes=5)      # plug-in at the car and session start within this time
FRESH = timedelta(hours=12)             # older battery values are not used
START_DELAY_S = 2                        # let the station receive its transaction ID first
TESLAMATE_KEYS = ("display_name", "battery_level", "charge_limit_soc", "plugged_in", "charging_state",
                  "rated_battery_range_km", "est_battery_range_km", "state")
SESSION_KEYS = {"display_name", "battery_level", "charge_limit_soc", "rated_battery_range_km",
                "est_battery_range_km"}


# --- Settings -----------------------------------------------------------------------------

@dataclass
class Settings:
    source: str = "off"
    topic: str = DEFAULT_TOPIC


async def settings() -> Settings:
    source = await licensing.get_setting("vehicle_source") or "off"
    topic = await licensing.get_setting("teslamate_topic") or DEFAULT_TOPIC
    return Settings(source if source in SOURCES else "off", topic)


async def configure(source: str, topic: str) -> Settings:
    await licensing.set_setting("vehicle_source", source if source in SOURCES else "off")
    await licensing.set_setting("teslamate_topic", topic.strip().strip("/") or DEFAULT_TOPIC)
    await restart()
    return await settings()


# --- Values from the source ---------------------------------------------------------------

def _bool(text: str) -> bool | None:
    t = text.strip().lower()
    return True if t in ("true", "1", "on") else False if t in ("false", "0", "off") else None


def _num(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_topic(prefix: str, topic: str) -> tuple[str, str] | None:
    """teslamate/cars/<id>/<key> -> (id, key)."""
    pre = prefix.strip("/").split("/")
    parts = topic.split("/")
    if (len(parts) != len(pre) + 3 or parts[:len(pre)] != pre or parts[len(pre)] != "cars"
            or parts[-1] not in TESLAMATE_KEYS):
        return None
    return parts[-2], parts[-1]


def apply(v: Vehicle, key: str, payload: str, now: datetime) -> bool:
    """Apply one TeslaMate value. Returns True if the car has just been plugged in."""
    newly_plugged = False
    if key == "display_name":
        v.name = payload.strip()[:100] or None
    elif key == "battery_level":
        v.soc = _num(payload)
    elif key == "charge_limit_soc":
        v.limit_soc = _num(payload)
    elif key == "rated_battery_range_km":
        v.range_km = _num(payload)
    elif key == "est_battery_range_km":
        if v.range_km is None:
            v.range_km = _num(payload)
    elif key == "plugged_in":
        plugged = _bool(payload)
        if plugged and v.plugged is False:
            v.plugged_since, newly_plugged = now, True
        elif not plugged:
            v.plugged_since = None
        # plugged and previously unknown (first message after setup): plug-in time unknown
        v.plugged = plugged
    elif key == "charging_state":
        v.charging_state = payload.strip()[:30] or None
    elif key == "state":
        v.state = payload.strip()[:30] or None
    v.updated = now
    return newly_plugged


def fresh_soc(v: Vehicle, now: datetime | None = None) -> float | None:
    if v.soc is None or v.updated is None or (now or utcnow()) - v.updated > FRESH:
        return None
    return max(0.0, min(100.0, v.soc))


async def handle(source: str, external_id: str, key: str, payload: str, now: datetime | None = None) -> int:
    """Store a value from the source, then update the session the car is charging in."""
    now = now or utcnow()
    async with Session() as s:
        v = (await s.execute(select(Vehicle).where(Vehicle.source == source,
                                                   Vehicle.external_id == external_id))).scalar_one_or_none()
        if v is None:
            v = Vehicle(source=source, external_id=external_id)
            s.add(v)
            log.info("New vehicle from %s: car %s", source, external_id)
        newly_plugged = apply(v, key, payload, now)
        await s.commit()
        vid = v.id
    if newly_plugged:
        await match_open_sessions(vid)
    elif key in SESSION_KEYS:
        await refresh_session(vid)
    return vid


# --- Which car is charging ------------------------------------------------------------------

def _near(v: Vehicle, started_at: datetime) -> bool:
    return bool(v.plugged and v.plugged_since and abs(v.plugged_since - started_at) <= PLUG_WINDOW)


def _reported_unplugged(v: Vehicle, started_at: datetime) -> bool:
    """The source said "not plugged in" around or after the session start – it's not this car (yet)."""
    return v.plugged is False and v.updated is not None and v.updated >= started_at - timedelta(minutes=1)


def pick(employee_id: int | None, started_at: datetime, cars: list[Vehicle],
         busy: set[int]) -> tuple[Vehicle | None, str]:
    """The car charging in a session. Returns (car or None, how: employee | plug_time | ambiguous | unknown)."""
    cars = [v for v in cars if v.id not in busy]
    own = [v for v in cars if employee_id is not None and v.employee_id == employee_id]
    if own:
        if len(own) > 1:
            own = ([v for v in own if _near(v, started_at)] or [v for v in own if v.plugged]) or own
        own = [v for v in own if not _reported_unplugged(v, started_at)]
        if len(own) == 1:
            return own[0], "employee"
        if len(own) > 1:
            return None, "ambiguous"
    near = [v for v in cars if _near(v, started_at)]
    if len(near) == 1:
        return near[0], "plug_time"
    return None, "ambiguous" if near else "unknown"


async def _busy(s) -> set[int]:
    return set((await s.execute(select(Transaction.vehicle_id).where(
        running_clause(), Transaction.vehicle_id.is_not(None)))).scalars())


async def assign_session(tx_id: int) -> int | None:
    """Find the car for a running session without one. Returns the car's ID."""
    async with Session() as s:
        tx = await s.get(Transaction, tx_id)
        if tx is None or tx.vehicle_id or tx.stopped_at or tx.late:
            return None
        cars = (await s.execute(select(Vehicle))).scalars().all()
        if not cars:
            return None
        v, how = pick(tx.employee_id, tx.started_at, list(cars), await _busy(s))
        if v is None:
            if how == "ambiguous":
                log.info("%s: several cars could be charging in session %s – assign it on the Vehicles page",
                         tx.station_id, tx.ocpp_tx_id)
            return None
        tx.vehicle_id, tx.vehicle_match = v.id, how
        await s.commit()
        log.info("%s: session %s – %s (%s)", tx.station_id, tx.ocpp_tx_id, v.label, how)
        vid = v.id
    await refresh_session(vid)
    return vid


async def match_open_sessions(vehicle_id: int) -> None:
    """A car was just plugged in: match it to a session that started around the same time."""
    async with Session() as s:
        v = await s.get(Vehicle, vehicle_id)
        if v is None or not v.plugged_since:
            return
        txs = (await s.execute(select(Transaction.id).where(
            running_clause(), Transaction.vehicle_id.is_(None),
            Transaction.started_at >= v.plugged_since - PLUG_WINDOW,
            Transaction.started_at <= v.plugged_since + PLUG_WINDOW))).scalars().all()
    for tx_id in txs:
        await assign_session(tx_id)


async def _on_start(tx_id: int) -> None:
    await asyncio.sleep(START_DELAY_S)
    try:
        await assign_session(tx_id)
    except Exception:  # noqa: BLE001
        log.exception("vehicle for session %s", tx_id)


async def set_session_vehicle(tx_id: int, vehicle_id: int | None) -> None:
    """Set the car of a session by hand (Vehicles page)."""
    async with Session() as s:
        tx = await s.get(Transaction, tx_id)
        if tx is None:
            return
        if vehicle_id:       # the car can only charge in one session at a time
            await s.execute(update(Transaction).where(running_clause(), Transaction.vehicle_id == vehicle_id,
                                                      Transaction.id != tx_id)
                            .values(vehicle_id=None, vehicle_match=None))
        if tx.vehicle_id != vehicle_id:
            tx.soc_start = tx.soc_last = None      # values of the previous car
        tx.vehicle_id, tx.vehicle_match = vehicle_id or None, "manual" if vehicle_id else None
        station_id, connector_id = tx.station_id, tx.connector_id
        if connector_id and (cs := await s.get(ConnectorStatus, (station_id, connector_id))):
            cs.soc = None
        await s.commit()
    if vehicle_id:
        await refresh_session(vehicle_id)
    else:
        await push(station_id, {"transactionId": _tx_ref(tx), "connectorId": connector_id})
        core.notify(station_id)


# --- Session values, stations ---------------------------------------------------------------

def _tx_ref(tx: Transaction) -> int | str:
    return int(tx.ocpp_tx_id) if (tx.ocpp_tx_id or "").isdigit() else tx.ocpp_tx_id


def info(tx: Transaction, v: Vehicle) -> dict:
    """What a station display shows (DataTransfer "VehicleInfo")."""
    soc = fresh_soc(v)
    return {"transactionId": _tx_ref(tx), "connectorId": tx.connector_id, "name": v.label,
            "soc": None if soc is None else round(soc),
            "limit": None if v.limit_soc is None else round(v.limit_soc),
            "rangeKm": None if v.range_km is None or soc is None else round(v.range_km)}


async def refresh_session(vehicle_id: int) -> None:
    """Battery level of a car -> the session it is charging in, Home Assistant and the station."""
    async with Session() as s:
        v = await s.get(Vehicle, vehicle_id)
        tx = (await s.execute(select(Transaction).options(selectinload(Transaction.station))
                              .where(Transaction.vehicle_id == vehicle_id, running_clause())
                              .order_by(Transaction.started_at.desc()).limit(1))).scalar_one_or_none()
        if v is None or tx is None:
            return
        soc = fresh_soc(v)
        if soc is not None:
            if tx.soc_start is None:
                tx.soc_start = soc
            tx.soc_last = soc
            if tx.connector_id and (cs := await s.get(ConnectorStatus, (tx.station_id, tx.connector_id))):
                cs.soc, cs.soc_supported = soc, True
        await s.commit()
        data, station = info(tx, v), tx.station
    core.notify(tx.station_id)
    if station is not None and station.is_kultiwb:
        await push(station.id, data)


async def info_for(station_id: str, tx_ref: str | None) -> dict | None:
    """The station asks (e.g. after a restart): car of its session, or of its running session."""
    async with Session() as s:
        stmt = (select(Transaction).options(selectinload(Transaction.vehicle))
                .where(Transaction.station_id == station_id, running_clause()))
        if tx_ref:
            stmt = stmt.where(Transaction.ocpp_tx_id == str(tx_ref))
        tx = (await s.execute(stmt.order_by(Transaction.started_at.desc()).limit(1))).scalar_one_or_none()
    if tx is None or tx.vehicle is None:
        return None
    _sent[(station_id, str(_tx_ref(tx)))] = json.dumps(info(tx, tx.vehicle))
    return info(tx, tx.vehicle)


_sent: dict[tuple[str, str], str] = {}


async def push(station_id: str, data: dict) -> None:
    """Send the car's values to a station with a display – only when they changed."""
    cp = core.connected.get(station_id)
    if cp is None or getattr(cp, "version", None) != "1.6":
        return
    text = json.dumps(data)
    key = (station_id, str(data.get("transactionId")))
    if _sent.get(key) == text:
        return
    from ocpp.v16 import call as c16
    try:
        res = await cp.call(c16.DataTransfer(vendor_id="ChargeGate", message_id="VehicleInfo", data=text))
        _sent[key] = text
        if len(_sent) > 500:
            _sent.clear()
        log.debug("%s: VehicleInfo %s -> %s", station_id, text, res.status)
    except Exception as exc:  # noqa: BLE001
        log.info("%s: could not send the battery level (%s)", station_id, exc)


# --- Source: TeslaMate via MQTT ---------------------------------------------------------------

class TeslaMateFeed:
    def __init__(self, topic: str):
        self.topic = topic.strip("/") or DEFAULT_TOPIC
        self.connected = False
        self.error: str | None = None
        self.last_message: datetime | None = None

    def subscriptions(self) -> list[str]:
        return [f"{self.topic}/cars/+/{k}" for k in TESLAMATE_KEYS]

    async def run(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(
                        hostname=config.MQTT_HOST, port=config.MQTT_PORT,
                        username=config.MQTT_USERNAME or None, password=config.MQTT_PASSWORD or None,
                        identifier="chargegate-vehicles") as client:
                    await client.subscribe([(t, 1) for t in self.subscriptions()])
                    self.connected, self.error = True, None
                    log.info("Vehicles: TeslaMate data from MQTT %s:%s, topic %s/cars/…",
                             config.MQTT_HOST, config.MQTT_PORT, self.topic)
                    async for msg in client.messages:
                        parsed = parse_topic(self.topic, str(msg.topic))
                        if parsed is None:
                            continue
                        self.last_message = utcnow()
                        payload = msg.payload.decode(errors="replace") if isinstance(msg.payload, bytes) \
                            else str(msg.payload or "")
                        try:
                            await handle("teslamate", parsed[0], parsed[1], payload)
                        except Exception:  # noqa: BLE001
                            log.exception("TeslaMate value %s", msg.topic)
            except asyncio.CancelledError:
                raise
            except aiomqtt.MqttError as exc:
                self.error = str(exc)
                log.warning("Vehicles: MQTT connection failed (%s) – retrying in 30 s", exc)
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                log.exception("Vehicles: TeslaMate feed error – retrying in 30 s")
            self.connected = False
            await asyncio.sleep(30)


feed: TeslaMateFeed | None = None
_task: asyncio.Task | None = None
_hooked = False


def mqtt_configured() -> bool:
    return bool(config.MQTT_ENABLED and config.MQTT_HOST)


async def restart() -> None:
    """(Re)start the source after a settings change or on start."""
    global feed, _task
    if _task:
        _task.cancel()
        _task = None
    feed = None
    st = await settings()
    if st.source == "teslamate" and mqtt_configured():
        feed = TeslaMateFeed(st.topic)
        _task = asyncio.create_task(feed.run())


async def start() -> None:
    global _hooked
    if not _hooked:
        core.on_session_start(_on_start)
        _hooked = True
    await restart()
