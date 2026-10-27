# ChargeGate – Home Assistant app

OCPP server (1.6J and 2.0.1) for company-wide RFID charging access. Employees hold their tag
against any station at any site; Home Assistant checks it centrally.

## Access

- **Web UI:** in the Home Assistant sidebar under **ChargeGate** (administrators only).
  Sign-in is handled by Home Assistant – no separate password needed.
- **Stations** connect to port **9000** of your Home Assistant host. The *Stations* page shows the
  exact address, e.g. `ws://192.168.1.10:9000/ocpp/` – the station appends its own ID.

Give Home Assistant a fixed IP address (DHCP reservation) and allow only TCP 9000 from the
station networks of all sites.

## Getting started

1. Start the app and open **ChargeGate** in the sidebar
2. Add your sites under **Stations**
3. Point a station to `ws://<home-assistant-ip>:9000/ocpp/` – it appears as *waiting for approval*
4. Approve it, give it a name and site, optionally set a basic auth password
5. Under **Employees & tags**, add employees – or hold a new tag against a station and assign it
   under *Unknown tags*

## Options

| Option | Meaning |
|---|---|
| Language | `auto` follows the browser, or force `en` / `de` |
| Require approval for new stations | Unknown stations are rejected until approved |
| Push tag list to stations | Valid tags are sent to the stations so charging works offline |
| Apply default station settings | Meter value interval, energy + power measurands and `StopTransactionOnInvalidId` (OCPP 1.6) |
| Heartbeat interval | Seconds between heartbeats requested from the stations |
| Meter value interval | How often stations send meter values while charging (default 60 s) |
| Publish to Home Assistant (MQTT) | Creates a device per station, see below |
| Employee shown in Home Assistant | `name`, `initials` or `hidden` |
| Install the charging point dashboard | Installs the dashboard card and creates the dashboard once |
| MQTT host/port/user/password | Only if you don't use the Mosquitto broker app |
| Log OCPP messages | For commissioning new station models; see the app's log tab |
| Password for direct access | Only if you enable port 8099 under *Network* |
| Entra settings | Import employees and tags from an Entra ID group, see below |

## Home Assistant entities

With the **Mosquitto broker** app and the **MQTT** integration installed, every approved station
appears as a device with status, charging, power, energy and the employee charging. Add the
**Energy** sensors under *Settings › Dashboards › Energy › Individual devices* to see where the
energy goes. If your stations are spread over several sites, tick **⚡ Energy dashboard** under
*Stations › Sites* only for the site of this Home Assistant – stations elsewhere are then not offered
as energy meters. Details: [docs/home-assistant.md](https://github.com/kultikom/chargegate/blob/main/docs/home-assistant.md)

## Charging point dashboard

The app installs the ChargeGate card and creates a dashboard **Charging points** with all stations:
state (incl. **Done** when a car has finished charging), live power bar (learns 11 or 22 kW),
session duration and employee. After the first
installation Home Assistant may ask for one restart. Turn it off with *Install the charging point
dashboard*.

## Station setup

See [docs/chargers.md](https://github.com/kultikom/chargegate/blob/main/docs/chargers.md) for
Compleo ducto and Alfen Eve Single. In short: backend URL as above, a unique charge box ID per
station, OCPP 1.6 JSON, optional basic auth with the password set in ChargeGate.

## Microsoft Entra ID (optional)

Create an app registration with the **application** permissions `User.Read.All` and
`GroupMember.Read.All` (grant admin consent) and a client secret. Enter tenant ID, client ID,
secret and the object ID of the group of employees allowed to charge. Tag UIDs are read from
`extensionAttribute10` (comma-separated for several tags). Employees who leave the group or are
disabled can no longer charge, and the tag list on the stations is updated automatically.
Details: [docs/entra-id.md](https://github.com/kultikom/chargegate/blob/main/docs/entra-id.md)

## Data and backup

All data is stored in an SQLite database in the app's data folder and is included in regular
Home Assistant backups.
