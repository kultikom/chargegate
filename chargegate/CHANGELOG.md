# Changelog

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
