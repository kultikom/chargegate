# Home Assistant entities and Energy dashboard

ChargeGate publishes every approved station to Home Assistant via **MQTT discovery**.
Each station becomes a device; the entities appear automatically.

## Requirements

- **Home Assistant app:** install the **Mosquitto broker** app and the **MQTT** integration.
  ChargeGate picks up the broker credentials from the Supervisor automatically – nothing to configure.
  Using another broker? Fill in `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`.
- **Standalone:** set `MQTT_ENABLED=true`, `MQTT_HOST` (and `MQTT_USERNAME` / `MQTT_PASSWORD`)
  to the broker your Home Assistant uses.

## Entities

Per station:

| Entity | Type | |
|---|---|---|
| Online | binary sensor (connectivity) | station connected to ChargeGate |

Per connector (prefixed with "Connector N" on stations with several connectors, e.g. Compleo Duo):

| Entity | Type | Unit | Notes |
|---|---|---|---|
| Status | sensor | | Available, Charging, Faulted, … |
| Charging | binary sensor | | a session is running |
| Power | sensor | W | needs `Power.Active.Import` in the meter values (set automatically for OCPP 1.6) |
| Energy | sensor | kWh | the station's energy register – `total_increasing` |
| Session energy | sensor | kWh | energy of the running session |
| Employee | sensor | | who is charging – see *Privacy* |

On the **ChargeGate** hub device: *Running sessions* and *Stations online*.

## Energy dashboard

**Settings › Dashboards › Energy › Individual devices › Add device** and pick the
**Energy** sensor of each connector. The dashboard then shows how much energy goes into each
charging point. The sensors use the stations' energy register, so nothing is lost when Home
Assistant or ChargeGate restarts.

Tip: for a smooth power reading, lower *Meter value interval* (default 60 s). Stations only send
meter values while charging.

## Privacy

Who is charging is personal data, and everyone with access to Home Assistant can see it.
Choose with the option **Employee shown in Home Assistant** (`HA_EMPLOYEE_DISPLAY`):

| Value | Shown |
|---|---|
| `name` | full name |
| `initials` | e.g. `M.T.` |
| `hidden` | no employee entity at all (an existing one is removed) |

The ChargeGate web UI always shows the full name to its admins.

## Topics

All messages are retained.

| Topic | Content |
|---|---|
| `chargegate/status` | `online` / `offline` (last will) |
| `chargegate/<station>/online` | `ON` / `OFF` |
| `chargegate/<station>/<connector>/state` | JSON: status, charging, power, energy, session_energy, employee |
| `chargegate/hub/state` | JSON: running, online |
| `homeassistant/…/config` | discovery |

Deleting a station in ChargeGate removes its device from Home Assistant.

## Example automation

Notify when a charging point is free again:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.duo_1_connector_1_charging
    from: "on"
    to: "off"
actions:
  - action: notify.notify
    data:
      message: "Charging point Duo 1 / 1 is free again"
```
