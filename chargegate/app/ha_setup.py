# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""One-time setup inside Home Assistant (only when running as a Home Assistant app).

1. Copy the ChargeGate dashboard card to <config>/www/chargegate/ (served as /local/…)
2. Register it as a dashboard resource (Lovelace storage mode)
3. Create a "Charging points" dashboard once – if the user deletes it, it is not recreated

Uses the Supervisor's proxy to the Home Assistant WebSocket API (homeassistant_api: true).
Everything here is best effort: failures are logged, ChargeGate keeps running.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import shutil
from pathlib import Path

import websockets

import config

log = logging.getLogger("chargegate.ha_setup")

CARD_SRC = Path(__file__).parent / "static" / "chargegate-card.js"
CARD_URL = f"/local/chargegate/chargegate-card.js?v={config.VERSION}"
DASHBOARD_PATH = "chargegate-live"
STATE_FILE = Path(os.getenv("ADDON_DATA", "/data")) / "ha_setup.json"


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state))
    except OSError as exc:
        log.warning("Could not save setup state: %s", exc)


def install_card_file() -> bool | None:
    """Copy the card into HA's www folder. Returns True if www had to be created (HA restart needed)."""
    root = Path(config.HA_CONFIG_DIR)
    if not (root / "configuration.yaml").exists():
        log.warning("Home Assistant config folder not found at %s – card not installed", root)
        return None
    www = root / "www"
    created = not www.exists()
    target = www / "chargegate" / "chargegate-card.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_bytes() != CARD_SRC.read_bytes():
        shutil.copyfile(CARD_SRC, target)
        log.info("Dashboard card installed to %s", target)
    return created


class HAWebSocket:
    def __init__(self, ws):
        self.ws, self._ids = ws, itertools.count(1)

    async def call(self, msg_type: str, **payload) -> object:
        msg_id = next(self._ids)
        await self.ws.send(json.dumps({"id": msg_id, "type": msg_type, **payload}))
        while True:
            reply = json.loads(await self.ws.recv())
            if reply.get("id") == msg_id:
                if not reply.get("success", False):
                    raise RuntimeError(f"{msg_type}: {reply.get('error')}")
                return reply.get("result")


def dashboard_config() -> dict:
    title = "Ladepunkte" if config.LANGUAGE == "de" else "Charging points"
    return {"title": title, "views": [{"title": title, "path": "live", "icon": "mdi:ev-station",
                                        "type": "panel", "cards": [{"type": "custom:chargegate-card"}]}]}


async def _setup(ws: HAWebSocket, www_created: bool | None) -> None:
    state = _load_state()

    # 2. resource
    try:
        resources = await ws.call("lovelace/resources")
        mine = [r for r in resources if str(r.get("url", "")).startswith("/local/chargegate/chargegate-card.js")]
        if not mine:
            await ws.call("lovelace/resources/create", res_type="module", url=CARD_URL)
            log.info("Dashboard resource registered: %s", CARD_URL)
        elif mine[0]["url"] != CARD_URL:
            await ws.call("lovelace/resources/update", resource_id=mine[0]["id"], res_type="module", url=CARD_URL)
            log.info("Dashboard resource updated: %s", CARD_URL)
    except RuntimeError as exc:
        log.warning("Could not register the dashboard resource (YAML mode?) – add %s manually (%s)", CARD_URL, exc)

    # 3. dashboard, once
    if not state.get("dashboard_created"):
        dashboards = await ws.call("lovelace/dashboards/list")
        if not any(d.get("url_path") == DASHBOARD_PATH for d in dashboards):
            cfg = dashboard_config()
            await ws.call("lovelace/dashboards/create", url_path=DASHBOARD_PATH, title=cfg["title"],
                          icon="mdi:ev-station", show_in_sidebar=True, require_admin=False, mode="storage")
            await ws.call("lovelace/config/save", url_path=DASHBOARD_PATH, config=cfg)
            log.info("Dashboard '%s' created", cfg["title"])
        state["dashboard_created"] = True
        _save_state(state)

    if www_created:
        de = config.LANGUAGE == "de"
        await ws.call("call_service", domain="persistent_notification", service="create", service_data={
            "notification_id": "chargegate_restart",
            "title": "ChargeGate",
            "message": ("Die Ladepunkt-Ansicht wurde installiert. Bitte Home Assistant einmal neu starten, "
                        "damit der Ordner www geladen wird.") if de else
                       ("The charging point dashboard was installed. Please restart Home Assistant once "
                        "so the www folder is picked up."),
        })


async def run() -> None:
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        return
    try:
        www_created = install_card_file()
    except OSError as exc:
        log.warning("Could not install the dashboard card: %s", exc)
        www_created = None
    for attempt in range(5):
        try:
            async with websockets.connect(config.HA_WEBSOCKET_URL, max_size=16 * 1024 * 1024) as raw:
                hello = json.loads(await raw.recv())
                if hello.get("type") == "auth_required":
                    await raw.send(json.dumps({"type": "auth", "access_token": token}))
                    if json.loads(await raw.recv()).get("type") != "auth_ok":
                        log.warning("Home Assistant rejected the Supervisor token")
                        return
                await _setup(HAWebSocket(raw), www_created)
                return
        except Exception as exc:  # noqa: BLE001
            log.warning("Home Assistant setup attempt %s failed: %s", attempt + 1, exc)
            await asyncio.sleep(20)


_task: asyncio.Task | None = None


def start() -> bool:
    global _task
    if not (config.HA_DASHBOARD and os.getenv("SUPERVISOR_TOKEN")):
        return False
    _task = asyncio.create_task(run())
    return True
