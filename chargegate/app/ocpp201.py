# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""OCPP 2.0.1 – CSMS."""
import asyncio
from datetime import UTC, datetime

from ocpp.routing import on
from ocpp.v201 import ChargePoint as CP201
from ocpp.v201 import call_result
from ocpp.v201.enums import Action, RegistrationStatusEnumType

import config
import core


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _token(id_token: dict | None) -> str | None:
    """Only count real tags, not 'NoAuthorization' and the like."""
    if not id_token or id_token.get("type") in ("NoAuthorization", "Central"):
        return None
    return id_token.get("id_token")


class ChargePoint201(CP201):
    version = "2.0.1"

    @on(Action.boot_notification)
    async def on_boot(self, charging_station, reason, **kw):
        await core.touch_station(
            self.id, vendor=charging_station.get("vendor_name"), model=charging_station.get("model"),
            serial=charging_station.get("serial_number"),
            firmware=charging_station.get("firmware_version"), ocpp_version="2.0.1")
        core.notify(self.id)  # vendor/model for the HA device
        if config.LOCAL_LIST_ENABLED or config.APPLY_STATION_CONFIG:
            asyncio.create_task(core.push_later(self.id))
        return call_result.BootNotification(current_time=_now(), interval=config.HEARTBEAT_INTERVAL,
                                            status=RegistrationStatusEnumType.accepted)

    @on(Action.heartbeat)
    async def on_heartbeat(self):
        await core.touch_station(self.id)
        return call_result.Heartbeat(current_time=_now())

    @on(Action.status_notification)
    async def on_status(self, timestamp, connector_status, evse_id, connector_id, **kw):
        await core.set_connector_status(self.id, evse_id, connector_status)
        return call_result.StatusNotification()

    @on(Action.authorize)
    async def on_authorize(self, id_token, **kw):
        status, _ = await core.authorize(self.id, id_token["id_token"])
        return call_result.Authorize(id_token_info={"status": status})

    @on(Action.transaction_event)
    async def on_transaction_event(self, event_type, timestamp, trigger_reason, seq_no,
                                   transaction_info, meter_value=None, id_token=None,
                                   evse=None, **kw):
        tx_id = transaction_info["transaction_id"]
        wh = core.energy_wh_from_meter_values(meter_value)
        w = core.power_w_from_meter_values(meter_value)
        soc = core.soc_from_meter_values(meter_value)
        uid = _token(id_token)
        status = emp_id = None
        ts = core.parse_ts(timestamp)
        if uid:
            status, emp_id = await core.authorize(self.id, uid, (evse or {}).get("id"), ts=ts)

        tx = await core.find_transaction(self.id, tx_id)
        if tx is None:
            # Also accept "Updated"/"Ended" without a prior "Started" (e.g. after a restart)
            tx = await core.start_transaction(
                self.id, (evse or {}).get("id"), uid, wh, ocpp_tx_id=tx_id,
                employee_id=emp_id, started_at=core.parse_ts(timestamp))
            if soc is not None:
                await core.update_transaction(self.id, tx_id, soc_last=soc)
        else:
            fields = {"meter_last_wh": wh, "soc_last": soc}
            if uid and not tx.tag_uid:      # cable plugged in first, tag presented afterwards
                fields.update(tag_uid=uid, employee_id=emp_id)
            await core.update_transaction(self.id, tx_id, **fields)

        connector = (evse or {}).get("id") or tx.connector_id
        if event_type == "Ended":
            await core.update_transaction(
                self.id, tx_id, stopped_at=core.parse_ts(timestamp), meter_stop_wh=wh,
                stop_reason=transaction_info.get("stopped_reason") or trigger_reason)
            w = 0.0
        await core.record_meter(self.id, connector, wh, w, soc, ts=ts)

        if status:
            return call_result.TransactionEvent(id_token_info={"status": status})
        return call_result.TransactionEvent()

    @on(Action.meter_values)
    async def on_meter_values(self, evse_id, meter_value, **kw):
        await core.record_meter(self.id, evse_id, core.energy_wh_from_meter_values(meter_value),
                                core.power_w_from_meter_values(meter_value),
                                core.soc_from_meter_values(meter_value),
                                ts=core.meter_values_ts(meter_value))
        await core.touch_station(self.id)
        return call_result.MeterValues()

    @on(Action.notify_report)
    async def on_notify_report(self, request_id, generated_at, seq_no, **kw):
        return call_result.NotifyReport()

    @on(Action.notify_event)
    async def on_notify_event(self, generated_at, seq_no, event_data, **kw):
        return call_result.NotifyEvent()

    @on(Action.security_event_notification)
    async def on_security_event(self, type, timestamp, **kw):
        return call_result.SecurityEventNotification()

    @on(Action.firmware_status_notification)
    async def on_fw_status(self, status, **kw):
        return call_result.FirmwareStatusNotification()

    @on(Action.log_status_notification)
    async def on_log_status(self, status, **kw):
        return call_result.LogStatusNotification()
