# Changelog

## 1.0.0

First release.

- OCPP 1.6J and 2.0.1 central system with RFID authorization across sites
- Web UI (English/German): stations, sites, employees & tags, sessions with kWh, authorization log
- Unknown tags can be assigned right from the UI after holding them against a station
- New stations must be approved; optional basic auth per station
- Local authorization list pushed to stations for offline operation
- Optional employee and tag sync from Microsoft Entra ID
- Runs as a Home Assistant app (ingress) or standalone with Docker
