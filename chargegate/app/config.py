"""Configuration – everything comes from environment variables (see .env.example)."""
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


VERSION = "1.0.0"

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./chargegate.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
TIMEZONE = os.getenv("TIMEZONE") or os.getenv("TZ") or "Europe/Berlin"
LANGUAGE = os.getenv("LANGUAGE_UI", "auto")  # auto | en | de

# Charging stations only talk to OCPP_PORT, admins only to WEB_PORT
OCPP_PORT = int(os.getenv("OCPP_PORT", "9000"))
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "300"))
LOG_OCPP_MESSAGES = _bool("LOG_OCPP_MESSAGES", False)

# Unknown stations show up as "pending" and are rejected until an admin approves them
REQUIRE_STATION_APPROVAL = _bool("REQUIRE_STATION_APPROVAL", True)
# Push the list of valid tags to the stations (SendLocalList) so charging works offline
LOCAL_LIST_ENABLED = _bool("LOCAL_LIST_ENABLED", True)
LOCAL_LIST_CHUNK = int(os.getenv("LOCAL_LIST_CHUNK", "100"))
# On connect: set meter value interval and StopTransactionOnInvalidId (OCPP 1.6)
APPLY_STATION_CONFIG = _bool("APPLY_STATION_CONFIG", True)

# Local admin login (empty = disabled)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# Home Assistant ingress: requests from these proxy IPs count as authenticated
INGRESS_TRUSTED_IPS = [ip.strip() for ip in os.getenv("INGRESS_TRUSTED_IPS", "").split(",") if ip.strip()]

# Microsoft Entra ID – admin login and employee sync
ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET = os.getenv("ENTRA_CLIENT_SECRET", "")
ENTRA_REDIRECT_URI = os.getenv("ENTRA_REDIRECT_URI", "")  # e.g. https://charge.example.com/auth/callback
ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID", "")

ENTRA_SYNC_GROUP_ID = os.getenv("ENTRA_SYNC_GROUP_ID", "")  # group of employees allowed to charge
ENTRA_RFID_ATTRIBUTE = os.getenv("ENTRA_RFID_ATTRIBUTE", "extensionAttribute10")
ENTRA_SYNC_INTERVAL_MIN = int(os.getenv("ENTRA_SYNC_INTERVAL_MIN", "60"))

_ENTRA_CREDS = bool(ENTRA_TENANT_ID and ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET)
# In the Home Assistant app, HA handles login; Entra is then used for the sync only
ENTRA_LOGIN_ENABLED = _ENTRA_CREDS and _bool("ENTRA_LOGIN", True)
ENTRA_SYNC_ENABLED = _ENTRA_CREDS and bool(ENTRA_SYNC_GROUP_ID)
