# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Charging station simulator for testing without real hardware.

  python sim.py --id TEST-01 --tag 04A2B3C4 --version 1.6
  python sim.py --id TEST-02 --tag 04A2B3C4 --version 2.0.1 --password geheim
"""
import argparse
import asyncio
import base64
import uuid
from datetime import UTC, datetime

import websockets
from ocpp.routing import on
from ocpp.v16 import ChargePoint as _CP16
from ocpp.v16 import call as c16
from ocpp.v16 import call_result as r16
from ocpp.v201 import ChargePoint as _CP201
from ocpp.v201 import call as c201
from ocpp.v201 import call_result as r201


class CP16(_CP16):
    @on("SendLocalList")
    async def on_list(self, list_version, update_type, local_authorization_list=None):
        print(f"Local list received ({update_type}): {[e['id_tag'] for e in local_authorization_list or []]}")
        return r16.SendLocalList(status="Accepted")

    @on("ClearCache")
    async def on_clear(self):
        print("Cache cleared")
        return r16.ClearCache(status="Accepted")


    @on("ChangeConfiguration")
    async def on_cfg(self, key, value):
        print(f"Configuration {key}={value}")
        return r16.ChangeConfiguration(status="Accepted")


class CP201(_CP201):
    @on("SendLocalList")
    async def on_list(self, version_number, update_type, local_authorization_list=None):
        uids = [e["id_token"]["id_token"] for e in local_authorization_list or []]
        print(f"Local list received ({update_type}): {uids}")
        return r201.SendLocalList(status="Accepted")

    @on("ClearCache")
    async def on_clear(self):
        print("Cache cleared")
        return r201.ClearCache(status="Accepted")


CONNECTOR = 1
SOC = None          # starting battery level in % (only sent if --soc is given)
BOOT = True         # send BootNotification (a reconnect after a server restart usually doesn't)
POWER = True        # report Power.Active.Import
STEP_DELAY = 0.5
FULL = 0.0          # seconds the car stays plugged in after it is full (power 0, SuspendedEV)


def now():
    return datetime.now(UTC).isoformat()


async def run16(cp, tag, kwh, steps):
    if BOOT:
        await cp.call(c16.BootNotification(charge_point_vendor="Simulator", charge_point_model="Sim16"))
    await cp.call(c16.StatusNotification(connector_id=CONNECTOR, error_code="NoError", status="Available"))
    res = await cp.call(c16.Authorize(id_tag=tag))
    print("Authorize:", res.id_tag_info["status"])
    if res.id_tag_info["status"] != "Accepted":
        return
    await cp.call(c16.StatusNotification(connector_id=CONNECTOR, error_code="NoError", status="Charging"))
    meter = 1_250_000
    start = await cp.call(c16.StartTransaction(connector_id=CONNECTOR, id_tag=tag, meter_start=meter, timestamp=now()))
    tx = start.transaction_id
    print("Transaction", tx)
    for _ in range(steps):
        await asyncio.sleep(STEP_DELAY)
        meter += int(kwh * 1000 / steps)
        sampled = [{"value": str(meter), "measurand": "Energy.Active.Import.Register", "unit": "Wh"}]
        if POWER:
            sampled.append({"value": "11000", "measurand": "Power.Active.Import", "unit": "W"})
        if SOC is not None:
            soc_now = min(100, SOC + (meter - 1_250_000) / 600)      # ~60 kWh battery
            sampled.append({"value": f"{soc_now:.0f}", "measurand": "SoC", "unit": "Percent", "location": "EV"})
        await cp.call(c16.MeterValues(connector_id=CONNECTOR, transaction_id=tx, meter_value=[{
            "timestamp": now(), "sampledValue": sampled}]))
    if FULL > 0:
        # car is full: it stops drawing power but stays plugged in
        await cp.call(c16.StatusNotification(connector_id=CONNECTOR, error_code="NoError", status="SuspendedEV"))
        print(f"Car full – staying plugged in for {FULL:.0f} s")
        waited = 0.0
        while waited < FULL:
            step = min(STEP_DELAY, FULL - waited)
            await asyncio.sleep(step)
            waited += step
            sampled = [{"value": str(meter), "measurand": "Energy.Active.Import.Register", "unit": "Wh"}]
            if POWER:
                sampled.append({"value": "0", "measurand": "Power.Active.Import", "unit": "W"})
            await cp.call(c16.MeterValues(connector_id=CONNECTOR, transaction_id=tx, meter_value=[{
                "timestamp": now(), "sampledValue": sampled}]))
    await cp.call(c16.StopTransaction(meter_stop=meter, timestamp=now(), transaction_id=tx, reason="EVDisconnected"))
    await cp.call(c16.StatusNotification(connector_id=CONNECTOR, error_code="NoError", status="Available"))
    print(f"Done, charged {kwh} kWh")


async def run201(cp, tag, kwh, steps):
    await cp.call(c201.BootNotification(charging_station={"model": "Sim201", "vendor_name": "Simulator"},
                                        reason="PowerUp"))
    await cp.call(c201.StatusNotification(timestamp=now(), connector_status="Available", evse_id=CONNECTOR, connector_id=1))
    res = await cp.call(c201.Authorize(id_token={"id_token": tag, "type": "ISO14443"}))
    print("Authorize:", res.id_token_info["status"])
    if res.id_token_info["status"] != "Accepted":
        return
    tx = str(uuid.uuid4())
    kwh_meter = 4200.0  # this simulator reports kWh to exercise unit conversion

    start_kwh = kwh_meter

    def mv(v):
        sampled = [{"value": round(v, 3), "measurand": "Energy.Active.Import.Register",
                    "unitOfMeasure": {"unit": "kWh"}},
                   {"value": 7.4, "measurand": "Power.Active.Import", "unitOfMeasure": {"unit": "kW"}}]
        if SOC is not None:
            sampled.append({"value": round(min(100, SOC + (v - start_kwh) / 0.6)), "measurand": "SoC",
                            "unitOfMeasure": {"unit": "Percent"}, "location": "EV"})
        return [{"timestamp": now(), "sampledValue": sampled}]

    await cp.call(c201.TransactionEvent(event_type="Started", timestamp=now(), trigger_reason="Authorized",
                                        seq_no=0, transaction_info={"transactionId": tx},
                                        id_token={"id_token": tag, "type": "ISO14443"},
                                        evse={"id": CONNECTOR, "connectorId": 1}, meter_value=mv(kwh_meter)))
    for i in range(steps):
        await asyncio.sleep(STEP_DELAY)
        kwh_meter += kwh / steps
        await cp.call(c201.TransactionEvent(event_type="Updated", timestamp=now(), trigger_reason="MeterValuePeriodic",
                                            seq_no=i + 1, transaction_info={"transactionId": tx},
                                            meter_value=mv(kwh_meter)))
    await cp.call(c201.TransactionEvent(event_type="Ended", timestamp=now(), trigger_reason="EVCommunicationLost",
                                        seq_no=steps + 1,
                                        transaction_info={"transactionId": tx, "stoppedReason": "EVDisconnected"},
                                        meter_value=mv(kwh_meter)))
    print(f"Done, charged {kwh} kWh")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://localhost:9000/ocpp")
    p.add_argument("--id", default="SIM-01")
    p.add_argument("--version", choices=["1.6", "2.0.1"], default="1.6")
    p.add_argument("--tag", default="04A2B3C4")
    p.add_argument("--password")
    p.add_argument("--kwh", type=float, default=7.5)
    p.add_argument("--steps", type=int, default=3)
    p.add_argument("--connector", type=int, default=1, help="connector (1.6) / EVSE (2.0.1) to use")
    p.add_argument("--soc", type=float, help="report the car's battery level, starting at this %%")
    p.add_argument("--no-boot", action="store_true", help="skip BootNotification (plain reconnect)")
    p.add_argument("--no-power", action="store_true", help="don't report power")
    p.add_argument("--step-delay", type=float, default=0.5, help="seconds between meter values")
    p.add_argument("--full", type=float, default=0, help="OCPP 1.6: stay plugged in N s after the car is full")
    p.add_argument("--stay", type=float, default=0, help="stay connected for N more seconds afterwards")
    a = p.parse_args()
    global CONNECTOR, SOC, BOOT, POWER, STEP_DELAY, FULL
    FULL = a.full
    CONNECTOR, SOC, BOOT, POWER, STEP_DELAY = a.connector, a.soc, not a.no_boot, not a.no_power, a.step_delay

    headers = {}
    if a.password:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{a.id}:{a.password}".encode()).decode()
    proto = "ocpp" + a.version
    async with websockets.connect(f"{a.url}/{a.id}", subprotocols=[proto], additional_headers=headers) as ws:
        cls = CP16 if a.version == "1.6" else CP201
        cp = cls(a.id, ws)
        listener = asyncio.create_task(cp.start())
        try:
            await (run16 if a.version == "1.6" else run201)(cp, a.tag, a.kwh, a.steps)
            await asyncio.sleep(a.stay)
        finally:
            listener.cancel()


if __name__ == "__main__":
    asyncio.run(main())
