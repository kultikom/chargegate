"""Entry point inside the Home Assistant app: map /data/options.json and Supervisor info to env vars."""
import asyncio
import ipaddress
import json
import logging
import os
import secrets
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, os.getenv("ADDON_APP_DIR", "/app"))

DATA = Path(os.getenv("ADDON_DATA", "/data"))
SUPERVISOR = os.getenv("SUPERVISOR_URL", "http://supervisor")
log = logging.getLogger("run")


def load_options() -> dict:
    try:
        return json.loads((DATA / "options.json").read_text())
    except FileNotFoundError:
        return {}


def secret_key() -> str:
    f = DATA / "secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


def supervisor(path: str) -> dict | None:
    """GET from the Supervisor API; None if not available (e.g. running outside HA)."""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        return None
    req = urllib.request.Request(f"{SUPERVISOR}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get("data")
    except Exception as exc:  # noqa: BLE001
        log.warning("Supervisor %s not available: %s", path, exc)
        return None


def public_ocpp_url() -> str:
    """ws://<host-ip>:<mapped port>/ocpp/ from the Supervisor's network and app info."""
    info = supervisor("/addons/self/info") or {}
    network = info.get("network") or {}
    if "9000/tcp" in network and not network["9000/tcp"]:
        return "disabled"
    port = network.get("9000/tcp") or 9000
    net = supervisor("/network/info") or {}
    candidates = []
    for iface in net.get("interfaces", []):
        if not iface.get("connected", True):
            continue
        for addr in (iface.get("ipv4") or {}).get("address") or []:
            ip = addr.split("/")[0]
            try:
                if ipaddress.ip_address(ip).is_loopback:
                    continue
            except ValueError:
                continue
            candidates.append((not iface.get("primary", False), ip))
    if not candidates:
        return ""
    return f"ws://{sorted(candidates)[0][1]}:{port}/ocpp/"


def mqtt_env(o: dict) -> dict:
    """MQTT broker: manual options win, otherwise credentials from the Supervisor (Mosquitto app)."""
    if not o.get("mqtt_enabled", True):
        return {"MQTT_ENABLED": "false"}
    if o.get("mqtt_host"):
        return {"MQTT_ENABLED": "true", "MQTT_HOST": o["mqtt_host"],
                "MQTT_PORT": str(o.get("mqtt_port") or 1883),
                "MQTT_USERNAME": o.get("mqtt_username") or "", "MQTT_PASSWORD": o.get("mqtt_password") or ""}
    svc = supervisor("/services/mqtt")
    if not svc or not svc.get("host"):
        log.warning("No MQTT broker found – install the Mosquitto broker app to see ChargeGate in Home Assistant")
        return {"MQTT_ENABLED": "false"}
    return {"MQTT_ENABLED": "true", "MQTT_HOST": svc["host"], "MQTT_PORT": str(svc.get("port", 1883)),
            "MQTT_USERNAME": svc.get("username") or "", "MQTT_PASSWORD": svc.get("password") or ""}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    o = load_options()
    os.environ.update({
        "DATABASE_URL": f"sqlite+aiosqlite:///{DATA}/chargegate.db",
        "SECRET_KEY": secret_key(),
        "OCPP_PORT": "9000",
        "WEB_PORT": "8099",
        "PUBLIC_OCPP_URL": os.getenv("PUBLIC_OCPP_URL") or public_ocpp_url(),
        # Requests through the HA ingress proxy (Supervisor) count as authenticated
        "INGRESS_TRUSTED_IPS": os.getenv("INGRESS_TRUSTED_IPS", "172.30.32.2"),
        "ADMIN_PASSWORD": o.get("admin_password") or "",
        "ENTRA_LOGIN": "false",
        "LANGUAGE_UI": o.get("language", "auto"),
        "REQUIRE_STATION_APPROVAL": str(o.get("require_station_approval", True)),
        "LOCAL_LIST_ENABLED": str(o.get("local_list_enabled", True)),
        "APPLY_STATION_CONFIG": str(o.get("apply_station_config", True)),
        "METER_VALUE_INTERVAL": str(o.get("meter_value_interval", 60)),
        "HEARTBEAT_INTERVAL": str(o.get("heartbeat_interval", 300)),
        "LOG_OCPP_MESSAGES": str(o.get("log_ocpp_messages", False)),
        "HA_EMPLOYEE_DISPLAY": o.get("employee_display", "name"),
        "HA_DASHBOARD": str(o.get("ha_dashboard", True)),
        "ENTRA_TENANT_ID": o.get("entra_tenant_id") or "",
        "ENTRA_CLIENT_ID": o.get("entra_client_id") or "",
        "ENTRA_CLIENT_SECRET": o.get("entra_client_secret") or "",
        "ENTRA_SYNC_GROUP_ID": o.get("entra_sync_group_id") or "",
        "ENTRA_RFID_ATTRIBUTE": o.get("entra_rfid_attribute") or "extensionAttribute10",
        "ENTRA_SYNC_INTERVAL_MIN": str(o.get("entra_sync_interval_min") or 60),
    })
    if not os.getenv("MQTT_HOST"):
        os.environ.update(mqtt_env(o))

    import main as app_main  # import only now so config.py sees the values
    asyncio.run(app_main.main())


if __name__ == "__main__":
    main()
