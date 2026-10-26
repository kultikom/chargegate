"""WebSocket endpoint for the charging stations (own port, reachable from station networks only).

URL to configure in the station: ws://<server>:9000/ocpp/<ChargeBoxId>
"""
import asyncio
import base64
import logging

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

import config
import core
from db import Session, Station, check_password, utcnow
from ocpp16 import ChargePoint16
from ocpp201 import ChargePoint201

log = logging.getLogger("chargegate")


class _Conn:
    """Adapter: the ocpp library expects recv()/send()."""

    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def recv(self) -> str:
        return await self.ws.receive_text()

    async def send(self, msg: str) -> None:
        await self.ws.send_text(msg)


def _basic_password(ws: WebSocket) -> str | None:
    header = ws.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        user_pass = base64.b64decode(header[6:]).decode()
        return user_pass.split(":", 1)[1]
    except Exception:
        return None


async def _check_station(station_id: str, ws: WebSocket) -> str | None:
    """Return a rejection reason, or None if the station may connect."""
    remote = ws.client.host if ws.client else None
    async with Session() as s:
        st = await s.get(Station, station_id)
        if st is None:
            s.add(Station(id=station_id, approved=not config.REQUIRE_STATION_APPROVAL,
                          remote_addr=remote, last_seen=utcnow()))
            await s.commit()
            if config.REQUIRE_STATION_APPROVAL:
                return "new station – waiting for approval"
            return None
        st.last_seen, st.remote_addr = utcnow(), remote
        await s.commit()
        if not st.approved:
            return "not approved"
        if st.password_hash:
            pw = _basic_password(ws)
            if pw is None or not check_password(pw, st.password_hash):
                return "basic auth failed"
    return None


async def ocpp_endpoint(ws: WebSocket):
    station_id = ws.path_params["station_id"].strip("/").split("/")[-1]
    offered = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]

    if "ocpp2.0.1" in offered:
        proto, cls = "ocpp2.0.1", ChargePoint201
    elif "ocpp1.6" in offered or not offered:
        proto, cls = ("ocpp1.6" if offered else None), ChargePoint16
    else:
        log.warning("%s only offers %s – not supported", station_id, offered)
        await ws.close(code=1002)
        return

    if reason := await _check_station(station_id, ws):
        log.warning("Rejected connection from %s: %s", station_id, reason)
        await ws.close(code=1008)
        return

    await ws.accept(subprotocol=proto)
    cp = cls(station_id, _Conn(ws))
    if old := core.connected.get(station_id):
        log.info("%s reconnected – replacing old connection", station_id)
        try:
            await old._connection.ws.close()
        except Exception:
            pass
    core.connected[station_id] = cp
    log.info("%s connected (OCPP %s)", station_id, cls.version)
    core.notify(station_id)
    if config.APPLY_STATION_CONFIG or config.LOCAL_LIST_ENABLED:
        asyncio.create_task(core.push_later(station_id, delay=8))
    try:
        await cp.start()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Error in connection %s", station_id)
    finally:
        if core.connected.get(station_id) is cp:
            core.connected.pop(station_id, None)
        await core.touch_station(station_id)
        core.notify(station_id)
        log.info("%s disconnected", station_id)


ocpp_app = Starlette(routes=[WebSocketRoute("/ocpp/{station_id:path}", ocpp_endpoint)])
