"""Version-independent logic: authorization, transactions, meter values, local list."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

import config
from db import (AuthEvent, ConnectorStatus, Employee, Session, Station, Tag,
                Transaction, normalize_uid, utcnow)

log = logging.getLogger("core")

# Connected stations: station_id -> ChargePoint object (in memory only)
connected: dict[str, object] = {}

ENERGY = "Energy.Active.Import.Register"
POWER = "Power.Active.Import"
CHARGING_STATES = {"Charging", "Occupied", "SuspendedEV", "SuspendedEVSE"}


# --- Change notifications (used by the Home Assistant / MQTT bridge) --------------------

_listeners: list = []


def add_listener(fn) -> None:
    """fn(station_id or None) is called after anything a station shows has changed."""
    _listeners.append(fn)


def notify(station_id: str | None) -> None:
    for fn in _listeners:
        try:
            fn(station_id)
        except Exception:  # noqa: BLE001
            log.exception("listener failed")


def notify_all() -> None:
    notify(None)


# --- Authorization ------------------------------------------------------------------

def _reverse_bytes(uid: str) -> str | None:
    if len(uid) % 2 or len(uid) < 4:
        return None
    return "".join(uid[i:i + 2] for i in range(len(uid) - 2, -1, -2))


async def authorize(station_id: str, raw_uid: str) -> tuple[str, int | None]:
    """Check a tag. Returns (OCPP status, employee_id)."""
    uid = normalize_uid(raw_uid)
    async with Session() as s:
        tag = (await s.execute(select(Tag).options(selectinload(Tag.employee))
                               .where(Tag.uid == uid))).scalar_one_or_none()
        reason = None
        if tag is None and (rev := _reverse_bytes(uid)):
            # Some readers report the UID in reversed byte order
            tag = (await s.execute(select(Tag).options(selectinload(Tag.employee))
                                   .where(Tag.uid == rev))).scalar_one_or_none()
            if tag:
                reason = "reversed_byte_order"

        if tag is None:
            status, emp_id, reason = "Invalid", None, "unknown_tag"
        elif not tag.active:
            status, emp_id, reason = "Blocked", tag.employee_id, "tag_blocked"
        elif not tag.employee.active:
            status, emp_id, reason = "Blocked", tag.employee_id, "employee_inactive"
        else:
            status, emp_id = "Accepted", tag.employee_id

        s.add(AuthEvent(station_id=station_id, tag_uid=uid, result=status,
                        reason=reason, employee_id=emp_id))
        await s.commit()
    log.info("Authorize %s @ %s -> %s (%s)", uid, station_id, status, reason or "ok")
    return status, emp_id


# --- Station state --------------------------------------------------------------------

async def touch_station(station_id: str, **fields) -> None:
    async with Session() as s:
        st = await s.get(Station, station_id)
        if st:
            st.last_seen = utcnow()
            for k, v in fields.items():
                if v is not None:
                    setattr(st, k, v)
            await s.commit()


async def set_connector_status(station_id: str, connector_id: int, status: str,
                               error_code: str | None = None) -> None:
    async with Session() as s:
        cs = await s.get(ConnectorStatus, (station_id, connector_id))
        if cs is None:
            cs = ConnectorStatus(station_id=station_id, connector_id=connector_id, status=status)
            s.add(cs)
        cs.status, cs.error_code, cs.updated = status, error_code, utcnow()
        if status not in CHARGING_STATES:
            cs.power_w = 0.0
        st = await s.get(Station, station_id)
        if st:
            st.last_seen = utcnow()
        await s.commit()
    notify(station_id)


async def record_meter(station_id: str, connector_id: int | None, energy_wh: float | None,
                       power_w: float | None = None) -> None:
    """Remember the latest energy register / power reading per connector."""
    if not connector_id or (energy_wh is None and power_w is None):
        return
    async with Session() as s:
        cs = await s.get(ConnectorStatus, (station_id, connector_id))
        if cs is None:
            cs = ConnectorStatus(station_id=station_id, connector_id=connector_id, status="Unknown")
            s.add(cs)
        if energy_wh is not None:
            cs.energy_wh = energy_wh
        if power_w is not None:
            cs.power_w = power_w
        await s.commit()
    notify(station_id)


# --- Transactions ---------------------------------------------------------------------

async def start_transaction(station_id: str, connector_id: int | None, raw_uid: str | None,
                            meter_wh: float | None, ocpp_tx_id: str | None = None,
                            employee_id: int | None = None,
                            started_at: datetime | None = None) -> Transaction:
    async with Session() as s:
        tx = Transaction(station_id=station_id, connector_id=connector_id,
                         started_at=started_at or utcnow(),
                         tag_uid=normalize_uid(raw_uid) if raw_uid else None,
                         employee_id=employee_id, meter_start_wh=meter_wh,
                         meter_last_wh=meter_wh, ocpp_tx_id=ocpp_tx_id)
        s.add(tx)
        await s.flush()
        if tx.ocpp_tx_id is None:          # OCPP 1.6: our primary key is the transactionId
            tx.ocpp_tx_id = str(tx.id)
        await s.commit()
    notify(station_id)
    return tx


async def find_transaction(station_id: str, ocpp_tx_id: str) -> Transaction | None:
    async with Session() as s:
        return (await s.execute(select(Transaction).where(
            Transaction.station_id == station_id,
            Transaction.ocpp_tx_id == str(ocpp_tx_id)))).scalar_one_or_none()


async def update_transaction(station_id: str, ocpp_tx_id: str, **fields) -> Transaction | None:
    async with Session() as s:
        tx = (await s.execute(select(Transaction).where(
            Transaction.station_id == station_id,
            Transaction.ocpp_tx_id == str(ocpp_tx_id)))).scalar_one_or_none()
        if tx is None:
            return None
        for k, v in fields.items():
            if v is None:
                continue
            if k == "meter_last_wh" and tx.meter_start_wh is None:
                tx.meter_start_wh = v
            setattr(tx, k, v)
        await s.commit()
    notify(station_id)
    return tx


def parse_ts(value: str | None) -> datetime:
    """Use the station's timestamp (matters for offline transactions), else server time."""
    if value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(UTC).replace(tzinfo=None)
            # Ignore implausible clocks (station without NTP)
            if abs((dt - utcnow()).days) < 30:
                return dt
        except ValueError:
            pass
    return utcnow()


# --- Meter values ---------------------------------------------------------------------

_FACTOR = {"wh": 1.0, "kwh": 1000.0, "w": 1.0, "kw": 1000.0}


def energy_wh_from_meter_values(meter_values: list | None) -> float | None:
    """Return the total energy register (Energy.Active.Import.Register) in Wh."""
    return _sampled(meter_values, ENERGY, "Wh")


def power_w_from_meter_values(meter_values: list | None) -> float | None:
    """Return the total active power (Power.Active.Import) in W."""
    return _sampled(meter_values, POWER, "W")


def _sampled(meter_values: list | None, measurand: str, default_unit: str) -> float | None:
    """Latest value of a measurand, converted to Wh or W.

    Works for 1.6 (value as string, unit) and 2.0.1 (value as number,
    unit_of_measure with multiplier). Per-phase values are ignored.
    """
    best = None
    for mv in meter_values or []:
        for sv in mv.get("sampled_value", []):
            if sv.get("measurand", ENERGY) != measurand or sv.get("phase"):
                continue
            if sv.get("format") == "SignedData" or "signed_meter_value" in sv:
                continue  # signed record for German calibration law (e.g. OCMF) – not numeric
            try:
                value = float(sv["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if "unit_of_measure" in sv:                       # 2.0.1
                uom = sv.get("unit_of_measure") or {}
                unit = (uom.get("unit") or default_unit).lower()
                value *= 10 ** int(uom.get("multiplier", 0))
            else:                                             # 1.6
                unit = (sv.get("unit") or default_unit).lower()
            best = value * _FACTOR.get(unit, 1.0)
    return best


# --- Local authorization list ---------------------------------------------------------
# Keeps charging possible during network/server outages. After every change the full
# list is re-sent and the station's authorization cache is cleared, so blocked tags
# don't keep working from the cache.

_push_task: asyncio.Task | None = None


async def active_uids() -> list[str]:
    async with Session() as s:
        rows = await s.execute(select(Tag.uid).join(Employee)
                               .where(Tag.active, Employee.active).order_by(Tag.uid))
        return [r[0] for r in rows]


async def push_local_list(station_id: str) -> str:
    """Returns 'ok:<count>', 'error:<message>' or 'offline'."""
    cp = connected.get(station_id)
    if cp is None:
        return "offline"
    from ocpp.v16 import call as c16
    from ocpp.v201 import call as c201

    uids = await active_uids()
    chunk = config.LOCAL_LIST_CHUNK
    parts = [uids[i:i + chunk] for i in range(0, len(uids), chunk)] or [[]]
    version = int(time.time()) % 2_000_000_000
    try:
        for n, part in enumerate(parts):
            update = "Full" if n == 0 else "Differential"
            if cp.version == "1.6":
                res = await cp.call(c16.SendLocalList(
                    list_version=version + n, update_type=update,
                    local_authorization_list=[{"id_tag": u, "id_tag_info": {"status": "Accepted"}} for u in part]))
            else:
                res = await cp.call(c201.SendLocalList(
                    version_number=version + n, update_type=update,
                    local_authorization_list=[{"id_token": {"id_token": u, "type": "ISO14443"},
                                               "id_token_info": {"status": "Accepted"}} for u in part]))
            if res.status != "Accepted":
                raise RuntimeError(f"station replied {res.status}")
        await cp.call(c16.ClearCache() if cp.version == "1.6" else c201.ClearCache())
        status = f"ok:{len(uids)}"
    except Exception as exc:  # noqa: BLE001
        status = f"error:{exc}"[:100]
    async with Session() as s:
        if st := await s.get(Station, station_id):
            st.local_list_pushed, st.local_list_status = utcnow(), status
            await s.commit()
    log.info("Local list to %s: %s", station_id, status)
    return status


def station_config_16() -> list[tuple[str, list[str]]]:
    """Standard OCPP 1.6 keys understood by all common stations (e.g. Compleo, Alfen).

    Each key has a list of values to try in order – the first accepted one wins.
    """
    return [
        ("MeterValueSampleInterval", [str(config.METER_VALUE_INTERVAL)]),
        # energy register + power; fall back to energy only if the station rejects power
        ("MeterValuesSampledData", [f"{ENERGY},{POWER}", ENERGY]),
        ("StopTransactionOnInvalidId", ["true"]),            # blocked tag -> charging stops
    ]


async def apply_station_config(station_id: str) -> None:
    cp = connected.get(station_id)
    if cp is None or cp.version != "1.6":
        return
    from ocpp.v16 import call as c16
    for key, values in station_config_16():
        for value in values:
            try:
                res = await cp.call(c16.ChangeConfiguration(key=key, value=value))
                log.info("%s: %s=%s -> %s", station_id, key, value, res.status)
                if res.status in ("Accepted", "RebootRequired"):
                    break
            except Exception as exc:  # noqa: BLE001
                log.warning("%s: could not set %s (%s)", station_id, key, exc)
                break


async def push_later(station_id: str, delay: float = 5) -> None:
    await asyncio.sleep(delay)
    if config.APPLY_STATION_CONFIG:
        await apply_station_config(station_id)
    if config.LOCAL_LIST_ENABLED:
        await push_local_list(station_id)


def schedule_push_all(delay: float = 15) -> None:
    """After changes: wait briefly to batch edits, then push to all connected stations."""
    global _push_task
    if not config.LOCAL_LIST_ENABLED:
        return
    if _push_task and not _push_task.done():
        _push_task.cancel()

    async def run():
        await asyncio.sleep(delay)
        for sid in list(connected):
            await push_local_list(sid)

    _push_task = asyncio.create_task(run())
