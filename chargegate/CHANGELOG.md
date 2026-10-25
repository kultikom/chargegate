# Changelog

## 1.2.1

- Overview and *Stations* page sort stations by name with natural number order ("Duo 2" before
  "Duo 10") instead of by charge box ID – the same order as the dashboard card. Sites are sorted by name.

## 1.2.0

- **Charging point dashboard:** new Home Assistant card `custom:chargegate-card` – all stations at a
  glance with state (offline / free / charging / connected / fault), live power bar, session duration
  and the employee charging. Responsive grid, follows the HA theme, English/German.
- The app installs the card, registers it as a dashboard resource and creates the dashboard
  "Charging points" once (option *Install the charging point dashboard*)
- The power bar learns each charging point's maximum: 11 kW, or 22 kW once more than 11.5 kW was measured
- The status sensor carries the full connector state as attributes (session start, learned maximum,
  station, site, online)

## 1.1.0

- **Home Assistant integration via MQTT discovery:** one device per station with status, charging,
  power, energy register (for the Energy dashboard), session energy and the employee charging
  ([#2](https://github.com/kultikom/chargegate/issues/2))
- New option *Employee shown in Home Assistant*: full name, initials or hidden
- New option *Meter value interval* (default 60 s); stations are asked for energy **and** power
- The *Stations* page shows the ready-to-use OCPP address with the host IP and port, including a
  copy button ([#3](https://github.com/kultikom/chargegate/issues/3))
- Name and email of manually created employees can be edited; tag labels can be edited
  ([#1](https://github.com/kultikom/chargegate/issues/1))
- Database schema is upgraded automatically on start-up – existing data is kept

## 1.0.0

First release.

- OCPP 1.6J and 2.0.1 central system with RFID authorization across sites
- Web UI (English/German): stations, sites, employees & tags, sessions with kWh, authorization log
- Unknown tags can be assigned right from the UI after holding them against a station
- New stations must be approved; optional basic auth per station
- Local authorization list pushed to stations for offline operation
- Optional employee and tag sync from Microsoft Entra ID
- Runs as a Home Assistant app (ingress) or standalone with Docker
