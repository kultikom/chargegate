"""OCPP 1.6J – Central System."""
import asyncio
from datetime import UTC, datetime

from ocpp.routing import on
from ocpp.v16 import ChargePoint as CP16
from ocpp.v16 import call_result
from ocpp.v16.enums import Action, DataTransferStatus, RegistrationStatus

import config
import core


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ChargePoint16(CP16):
    version = "1.6"

    @on(Action.boot_notification)
    async def on_boot(self, charge_point_vendor, charge_point_model, **kw):
        await core.touch_station(
            self.id, vendor=charge_point_vendor, model=charge_point_model,
            serial=kw.get("charge_point_serial_number") or kw.get("charge_box_serial_number"),
            firmware=kw.get("firmware_version"), ocpp_version="1.6")
        core.notify(self.id)  # vendor/model for the HA device
        if config.LOCAL_LIST_ENABLED or config.APPLY_STATION_CONFIG:
            asyncio.create_task(core.push_later(self.id))
        return call_result.BootNotification(current_time=_now(), interval=config.HEARTBEAT_INTERVAL,
                                            status=RegistrationStatus.accepted)

    @on(Action.heartbeat)
    async def on_heartbeat(self):
        await core.touch_station(self.id)
        return call_result.Heartbeat(current_time=_now())

    @on(Action.status_notification)
    async def on_status(self, connector_id, error_code, status, **kw):
        await core.set_connector_status(self.id, connector_id, status,
                                        None if error_code == "NoError" else error_code)
        return call_result.StatusNotification()

    @on(Action.authorize)
    async def on_authorize(self, id_tag):
        status, _ = await core.authorize(self.id, id_tag)
        return call_result.Authorize(id_tag_info={"status": status})

    @on(Action.start_transaction)
    async def on_start(self, connector_id, id_tag, meter_start, timestamp, **kw):
        status, emp_id = await core.authorize(self.id, id_tag, connector_id)
        tx = await core.start_transaction(self.id, connector_id, id_tag, float(meter_start),
                                          employee_id=emp_id, started_at=core.parse_ts(timestamp))
        await core.record_meter(self.id, connector_id, float(meter_start))
        return call_result.StartTransaction(transaction_id=tx.id, id_tag_info={"status": status})

    @on(Action.stop_transaction)
    async def on_stop(self, meter_stop, timestamp, transaction_id, **kw):
        soc = core.soc_from_meter_values(kw.get("transaction_data"))
        tx = await core.update_transaction(self.id, str(transaction_id), meter_stop_wh=float(meter_stop),
                                           meter_last_wh=float(meter_stop), soc_last=soc,
                                           stopped_at=core.parse_ts(timestamp),
                                           stop_reason=kw.get("reason") or "Local")
        if tx:
            await core.record_meter(self.id, tx.connector_id, float(meter_stop), 0.0)
        if kw.get("id_tag"):
            return call_result.StopTransaction(id_tag_info={"status": "Accepted"})
        return call_result.StopTransaction()

    @on(Action.meter_values)
    async def on_meter_values(self, connector_id, meter_value, transaction_id=None, **kw):
        wh = core.energy_wh_from_meter_values(meter_value)
        w = core.power_w_from_meter_values(meter_value)
        soc = core.soc_from_meter_values(meter_value)
        if transaction_id is not None and (wh is not None or soc is not None):
            await core.update_transaction(self.id, str(transaction_id), meter_last_wh=wh, soc_last=soc)
        await core.record_meter(self.id, connector_id, wh, w, soc)
        await core.touch_station(self.id)
        return call_result.MeterValues()

    @on(Action.data_transfer)
    async def on_data_transfer(self, vendor_id, **kw):
        return call_result.DataTransfer(status=DataTransferStatus.unknown_vendor_id)

    @on(Action.firmware_status_notification)
    async def on_fw_status(self, status, **kw):
        return call_result.FirmwareStatusNotification()

    @on(Action.diagnostics_status_notification)
    async def on_diag_status(self, status, **kw):
        return call_result.DiagnosticsStatusNotification()
