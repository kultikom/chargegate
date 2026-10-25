"""Entry point inside the Home Assistant app: map /data/options.json to environment variables."""
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, os.getenv("ADDON_APP_DIR", "/app"))

DATA = Path(os.getenv("ADDON_DATA", "/data"))


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


def main() -> None:
    o = load_options()
    os.environ.update({
        "DATABASE_URL": f"sqlite+aiosqlite:///{DATA}/chargegate.db",
        "SECRET_KEY": secret_key(),
        "OCPP_PORT": "9000",
        "WEB_PORT": "8099",
        # Requests through the HA ingress proxy (Supervisor) count as authenticated
        "INGRESS_TRUSTED_IPS": os.getenv("INGRESS_TRUSTED_IPS", "172.30.32.2"),
        "ADMIN_PASSWORD": o.get("admin_password") or "",
        "ENTRA_LOGIN": "false",
        "LANGUAGE_UI": o.get("language", "auto"),
        "REQUIRE_STATION_APPROVAL": str(o.get("require_station_approval", True)),
        "LOCAL_LIST_ENABLED": str(o.get("local_list_enabled", True)),
        "APPLY_STATION_CONFIG": str(o.get("apply_station_config", True)),
        "HEARTBEAT_INTERVAL": str(o.get("heartbeat_interval", 300)),
        "LOG_OCPP_MESSAGES": str(o.get("log_ocpp_messages", False)),
        "ENTRA_TENANT_ID": o.get("entra_tenant_id") or "",
        "ENTRA_CLIENT_ID": o.get("entra_client_id") or "",
        "ENTRA_CLIENT_SECRET": o.get("entra_client_secret") or "",
        "ENTRA_SYNC_GROUP_ID": o.get("entra_sync_group_id") or "",
        "ENTRA_RFID_ATTRIBUTE": o.get("entra_rfid_attribute") or "extensionAttribute10",
        "ENTRA_SYNC_INTERVAL_MIN": str(o.get("entra_sync_interval_min") or 60),
    })

    import main as app_main  # import only now so config.py sees the values
    asyncio.run(app_main.main())


if __name__ == "__main__":
    main()
