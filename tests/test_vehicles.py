# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Vehicles: TeslaMate values, matching cars to sessions, battery level in sessions.

  python -m pytest tests -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "chargegate" / "app"
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
sys.path.insert(0, str(APP))

import core  # noqa: E402
import vehicles  # noqa: E402
from db import Employee, Session, Tag, Transaction, Vehicle, init_db, utcnow  # noqa: E402

vehicles.START_DELAY_S = 0


def car(id_, employee_id=None, plugged=None, plugged_since=None, updated=None):
    v = Vehicle(source="teslamate", external_id=str(id_), employee_id=employee_id, plugged=plugged,
                plugged_since=plugged_since, updated=updated)
    v.id = id_
    return v


def test_parse_topic():
    assert vehicles.parse_topic("teslamate", "teslamate/cars/2/battery_level") == ("2", "battery_level")
    assert vehicles.parse_topic("home/tm", "home/tm/cars/1/plugged_in") == ("1", "plugged_in")
    assert vehicles.parse_topic("teslamate", "teslamate/cars/2/odometer") is None
    assert vehicles.parse_topic("teslamate", "other/cars/2/battery_level") is None


def test_plugged_since_only_on_a_real_change():
    now = utcnow()
    v = car(1)
    assert vehicles.apply(v, "plugged_in", "true", now) is False       # first value: time unknown
    assert v.plugged and v.plugged_since is None
    vehicles.apply(v, "plugged_in", "false", now)
    assert vehicles.apply(v, "plugged_in", "true", now + timedelta(minutes=1)) is True
    assert v.plugged_since == now + timedelta(minutes=1)


def test_pick():
    t0 = utcnow()
    near = t0 + timedelta(seconds=40)
    a = car(1, employee_id=10)
    b = car(2, plugged=True, plugged_since=near)
    c = car(3, employee_id=11, plugged=True, plugged_since=t0 - timedelta(hours=2))
    # the employee's car
    assert vehicles.pick(10, t0, [a, b, c], set()) == (a, "employee")
    # no car of their own: the one plugged in at the same time
    assert vehicles.pick(99, t0, [a, b, c], set()) == (b, "plug_time")
    assert vehicles.pick(None, t0, [a, b, c], set()) == (b, "plug_time")
    # never twice
    assert vehicles.pick(99, t0, [a, b, c], {2}) == (None, "unknown")
    # two cars plugged in at the same moment -> ambiguous
    d = car(4, plugged=True, plugged_since=near)
    assert vehicles.pick(99, t0, [b, d], set()) == (None, "ambiguous")
    # own car reported "not plugged in" right now -> not this car (yet), fall back to plug time
    a2 = car(1, employee_id=10, plugged=False, updated=t0)
    assert vehicles.pick(10, t0, [a2, b], set()) == (b, "plug_time")
    # two own cars: the one plugged in
    e = car(5, employee_id=10, plugged=True, plugged_since=near)
    assert vehicles.pick(10, t0, [a, e], set()) == (e, "employee")


def test_session_gets_car_and_battery_level():
    async def run():
        await init_db()
        await vehicles.start()                       # source off: no feed, but the start hook
        async with Session() as s:
            emp = Employee(name="Anna Beispiel")
            emp.tags.append(Tag(uid="CAFE0001"))
            s.add(emp)
            await s.commit()
            emp_id = emp.id
        # TeslaMate reports the car before the session
        vid = await vehicles.handle("teslamate", "1", "display_name", "Testwagen")
        await vehicles.handle("teslamate", "1", "battery_level", "41")
        async with Session() as s:
            (await s.get(Vehicle, vid)).employee_id = emp_id
            await s.commit()
        tx = await core.start_transaction("ST1", 1, "CAFE0001", 1000.0, employee_id=emp_id)
        for _ in range(50):
            await asyncio.sleep(0.05)
            async with Session() as s:
                t = await s.get(Transaction, tx.id)
            if t.vehicle_id:
                break
        assert t.vehicle_id == vid and t.vehicle_match == "employee"
        assert t.soc_start == 41 and t.soc_last == 41
        await vehicles.handle("teslamate", "1", "battery_level", "57")
        async with Session() as s:
            t = await s.get(Transaction, tx.id)
        assert (t.soc_start, t.soc_last) == (41, 57)
        info = await vehicles.info_for("ST1", tx.ocpp_tx_id)
        assert info["name"] == "Testwagen" and info["soc"] == 57 and info["transactionId"] == tx.id

        # second car without employee, plugged in shortly after a session started -> matched later
        tx2 = await core.start_transaction("ST2", 1, "ABCD9999", 0.0)
        await asyncio.sleep(0.1)
        v2 = await vehicles.handle("teslamate", "2", "plugged_in", "false")
        await vehicles.handle("teslamate", "2", "battery_level", "70")
        await vehicles.handle("teslamate", "2", "plugged_in", "true")
        async with Session() as s:
            t2 = await s.get(Transaction, tx2.id)
        assert t2.vehicle_id == v2 and t2.vehicle_match == "plug_time" and t2.soc_start == 70

        # set by hand: the car moves to the other session
        await vehicles.set_session_vehicle(tx2.id, vid)
        async with Session() as s:
            t, t2 = await s.get(Transaction, tx.id), await s.get(Transaction, tx2.id)
        assert t.vehicle_id is None and t2.vehicle_id == vid and t2.vehicle_match == "manual"
        assert t2.soc_start == 57
    asyncio.run(run())
