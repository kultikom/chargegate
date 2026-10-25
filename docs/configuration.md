# Configuration reference

The standalone version is configured with environment variables (see `.env.example`).
The Home Assistant app maps its options to the same variables.

| Variable | HA option | Default | Meaning |
|---|---|---|---|
| `DATABASE_URL` | – | SQLite in `/data` | SQLAlchemy URL, e.g. `postgresql+asyncpg://…` |
| `SECRET_KEY` | – (generated) | – | signs session cookies |
| `TIMEZONE` | – (HA time zone) | `Europe/Berlin` | display time zone |
| `LANGUAGE_UI` | `language` | `auto` | `auto`, `en` or `de` |
| `OCPP_PORT` | – | `9000` | WebSocket port for stations |
| `WEB_PORT` | – | `8080` (HA: `8099`) | web UI port |
| `HEARTBEAT_INTERVAL` | `heartbeat_interval` | `300` | seconds |
| `METER_VALUE_INTERVAL` | `meter_value_interval` | `60` | seconds between meter values while charging |
| `PUBLIC_OCPP_URL` | – (from Supervisor) | from request | OCPP address shown in the UI |
| `REQUIRE_STATION_APPROVAL` | `require_station_approval` | `true` | reject unknown stations until approved |
| `LOCAL_LIST_ENABLED` | `local_list_enabled` | `true` | push valid tags to stations |
| `LOCAL_LIST_CHUNK` | – | `100` | tags per SendLocalList message |
| `APPLY_STATION_CONFIG` | `apply_station_config` | `true` | meter interval + StopTransactionOnInvalidId |
| `LOG_OCPP_MESSAGES` | `log_ocpp_messages` | `false` | log raw OCPP traffic |
| `ADMIN_PASSWORD` | `admin_password` | `admin` (HA: empty) | local login; empty disables it |
| `INGRESS_TRUSTED_IPS` | – | empty (HA: Supervisor) | proxy IPs whose ingress headers are trusted |
| `MQTT_ENABLED` | `mqtt_enabled` | `false` (HA: `true`) | publish to Home Assistant |
| `MQTT_HOST`, `MQTT_PORT` | `mqtt_host`, `mqtt_port` | – / `1883` | HA: from the Mosquitto app |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | `mqtt_username`, `mqtt_password` | – | |
| `MQTT_BASE_TOPIC` | – | `chargegate` | |
| `MQTT_DISCOVERY_PREFIX` | – | `homeassistant` | |
| `HA_EMPLOYEE_DISPLAY` | `employee_display` | `name` | `name`, `initials` or `hidden` |
| `ENTRA_TENANT_ID` | `entra_tenant_id` | – | |
| `ENTRA_CLIENT_ID` | `entra_client_id` | – | |
| `ENTRA_CLIENT_SECRET` | `entra_client_secret` | – | |
| `ENTRA_SYNC_GROUP_ID` | `entra_sync_group_id` | – | enables the employee sync |
| `ENTRA_RFID_ATTRIBUTE` | `entra_rfid_attribute` | `extensionAttribute10` | |
| `ENTRA_SYNC_INTERVAL_MIN` | `entra_sync_interval_min` | `60` | |
| `ENTRA_REDIRECT_URI` | – | – | standalone admin sign-in with Microsoft |
| `ADMIN_EMAILS`, `ADMIN_GROUP_ID` | – | – | who may sign in with Microsoft |

## Network

- **Port 9000 (OCPP):** reachable from the station networks only
- **Web UI:** internal only; behind a reverse proxy with HTTPS in production.
  In Home Assistant it is reached through the sidebar (ingress).
- ChargeGate speaks plain `ws://`. For stations connecting over the internet, terminate TLS
  (`wss://`) in a reverse proxy and use basic auth per station.
