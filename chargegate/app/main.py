# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Run the OCPP server (stations) and the web UI (admins) in one process."""
import asyncio
import logging

import uvicorn

import config
import core
import licensing
import ha_mqtt
import ha_setup
import vehicles
from db import init_db
from ocpp_server import ocpp_app
from web import web_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
# Raw OCPP messages only on demand (commissioning new station models)
logging.getLogger("ocpp").setLevel(logging.INFO if config.LOG_OCPP_MESSAGES else logging.WARNING)


async def main():
    await init_db()
    await licensing.start()
    if n := await core.backfill_auth_connectors():
        logging.info("Added the charging point to %s older log entries", n)
    servers = [
        uvicorn.Server(uvicorn.Config(ocpp_app, host="0.0.0.0", port=config.OCPP_PORT,
                                      ws_ping_interval=60, ws_ping_timeout=60, log_level="warning",
                                      ws_max_size=1_048_576)),     # OCPP messages are a few KB
        uvicorn.Server(uvicorn.Config(web_app, host="0.0.0.0", port=config.WEB_PORT,
                                      proxy_headers=True, log_level="warning")),
    ]
    logging.info("ChargeGate %s – OCPP on port %s, web UI on port %s", config.VERSION, config.OCPP_PORT, config.WEB_PORT)
    if config.INGRESS_TRUSTED_IPS:
        logging.info("Login via Home Assistant ingress%s",
                     ", direct access with password" if config.ADMIN_PASSWORD else "")
    elif not config.ENTRA_LOGIN_ENABLED:
        logging.warning("Entra login not configured – local admin login active")
    if config.ADMIN_PASSWORD_GENERATED:
        logging.warning("No ADMIN_PASSWORD set – generated one: %s (stored in %s/admin_password; "
                        "set ADMIN_PASSWORD to choose your own)", config.ADMIN_PASSWORD, config.DATA_DIR)
    elif config.ADMIN_PASSWORD and len(config.ADMIN_PASSWORD) < 10:
        logging.warning("The admin password is short – use at least 10 characters")
    if ha_setup.start():
        logging.info("Setting up the ChargeGate dashboard in Home Assistant")
    if ha_mqtt.start():
        logging.info("Home Assistant via MQTT: %s:%s", config.MQTT_HOST, config.MQTT_PORT)
    await vehicles.start()
    async def license_loop():          # dates move on: expiring, grace, expired
        while True:
            await asyncio.sleep(600)
            try:
                await licensing.refresh()
            except Exception:  # noqa: BLE001
                logging.exception("license refresh")

    await asyncio.gather(license_loop(), *(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
