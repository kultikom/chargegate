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
| Status | sensor | | Available, Charging, Faulted, …, `Offline` – stays available while the station is offline and carries the full connector state as attributes |
| Charging | binary sensor | | a session is running |
| Power | sensor | W | needs `Power.Active.Import` in the meter values (set automatically for OCPP 1.6) |
| Energy | sensor | kWh | the station's energy register – `total_increasing` |
| Session energy | sensor | kWh | energy of the running session |
| Employee | sensor | | who is charging – see *Privacy* |

On the **ChargeGate** hub device: *Running sessions* and *Stations online*.

## Charging point dashboard

![Charging point dashboard](images/dashboard.png)

The card `custom:chargegate-card` shows every charging point with

- **state:** offline, free, charging, connected (session running but no power flowing, e.g. car full), fault
- **live power** as a bar, scaled to the charging point's maximum – learned automatically: 11 kW,
  or 22 kW as soon as more than 11.5 kW was measured once (stored, survives restarts)
- **session duration**, counting live
- **employee** charging (respecting the privacy option below)

**Home Assistant app:** with *Install the charging point dashboard* enabled (default), ChargeGate copies
the card to `/config/www/chargegate/`, registers it as a dashboard resource and creates the dashboard
**Charging points** once. If the `www` folder did not exist before, Home Assistant shows a notification
asking for one restart. The dashboard is yours afterwards – edit or delete it, it won't be recreated.

**Standalone / manual:** copy `chargegate/app/static/chargegate-card.js` to `/config/www/chargegate/`,
add `/local/chargegate/chargegate-card.js` as a *JavaScript module* under
*Settings › Dashboards › ⋮ › Resources*, then add the card:

```yaml
type: custom:chargegate-card
title: Charging points        # optional
site: Head office             # optional: only stations of this site
stations: [DUO-01, EVE-01]    # optional: only these station IDs, in this order
columns: 2                    # optional: fixed number of columns (default: responsive)
show_employee: true           # optional
```

For a full-screen view (e.g. a wall tablet) put it into a view of type **Panel**.

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
