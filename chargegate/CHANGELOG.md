# Changelog

## 1.9.0

- **New license: Business Source License 1.1** (KultiKom GmbH & Co. KG). Free for production use with
  up to 2 charging points and for evaluation/testing; a commercial license is required beyond that.
  Each version becomes Apache-2.0 four years after its release. Versions up to 1.8.2 remain MIT.
- No functional changes

## 1.8.2

- **Fix: a charging station was shown as *Free* although a car was charging.** While a station is
  still sending its offline queue, the start of a new session waits behind the old messages (OCPP
  sends transaction messages strictly in order), but status messages arrive at once. Without a known
  session ChargeGate ignored the `Charging` status. Now the station's status counts: *Charging*,
  *Paused* or *Connected*, with the employee who just presented a tag there (last 15 minutes).
- When the delayed start finally arrives, the session counts as running (with its real start time)
  as long as the connector is still busy; old replayed sessions that are still open are ignored

## 1.8.1

- Dashboard card: the **site is chosen in the card editor** (edit mode) – viewers can't switch it.
  Site tabs are now **off by default** and only appear if *Viewers may switch sites* is ticked.

## 1.8.0

- **Dashboard card: site tabs.** With stations at several sites the card shows tabs
  "All · Site A · Site B …" (with the number of busy charging points). The choice is remembered per
  browser – a wall tablet at one site keeps showing that site.
- **Visual card editor:** pick a fixed site, the tab selected at first, columns and what to show –
  no YAML needed
- New card options `sites`, `default_site`, `show_site_tabs`

## 1.7.2

- *Sessions*: a notice points to sessions a station sent afterwards in the last 14 days – they are
  listed in the month they happened, not in the current month

## 1.7.1

- **Fix: employee search** matched almost everybody – the query was also compared with tag UIDs
  after removing all non-hex letters ("Jonas" became "A"). Tag UIDs are now only searched when the
  query looks like a UID (at least 4 hex digits, colons/spaces allowed).
- *Employees & tags*: the form for new employees is now above the list; the search shows how many
  employees match and has a *Reset* button

## 1.7.0

- **Energy dashboard per site:** under *Stations › Sites* each site has a switch *Energy dashboard*.
  Only stations of ticked sites are published as energy meters (`device_class: energy`,
  `state_class: total_increasing`) and can be added to this Home Assistant's Energy dashboard.
  Stations at other sites keep all other entities and stay in the charging point card – their charging
  is simply not counted as this building's consumption. Default: ticked (as before).

## 1.6.0

- **Fix: sessions sent afterwards keep their real date.** Stations with an offline queue (seen on an
  Alfen Eve that replayed sessions back to 2022) send old sessions when they connect. ChargeGate
  ignored timestamps older than 30 days and stored them with the current time. Now the station's time
  is used (anything from 2010 up to one day ahead); such sessions are marked **sent afterwards**.
- Old meter readings from the queue no longer overwrite the live energy register (which made the
  Home Assistant energy sensor jump backwards)
- A stop for a session that started under a previous backend is rebuilt from its `transactionData`
- A new session on a connector closes an older one that never received its stop
- **Deleting sessions:** tick sessions and delete them, or delete everything matching the current
  filter; *Clean up* deletes finished sessions and/or log entries before a date
- *Sessions* page: filter by station, period list contains every month with data plus *all*

## 1.5.0

- **"Done" state:** a car that has charged and then drawn no power for 3 minutes is shown as
  **Done** – in the dashboard card (with "for 0:41:00": how long it has been standing there full),
  in the ChargeGate overview and as new Home Assistant entity **State**
- **Paused** when the station itself holds back (`SuspendedEVSE`, e.g. load management)
- The card summary counts finished cars ("1 charging · 1 done · 10.1 kW")
- New entity **State** per charging point: Free / Charging / Done / Paused / Connected / Fault /
  Offline, with the code in attribute `phase` for automations

## 1.4.1

- **Fix:** station settings (meter value interval, power measurand) and the tag list are now sent on
  every connection – before, only after a station *booted*. Stations that merely reconnected after
  a ChargeGate update never received them and reported no power.
- **Fix:** the dashboard card trusts the station's own status: a connector reporting `Charging` is
  shown as charging even before the first power reading (was shown as "Connected")
- Stations that don't report power get it estimated from their energy register
- The state badge in the card shows the raw OCPP status as tooltip

## 1.4.0

- **Charging point in the log:** the *Log* page shows at which charging point a tag was used.
  An `Authorize` followed by the session start now gives one log entry instead of two. Existing
  entries get their charging point from the matching session on start-up.
- **Charging point names** per station, e.g. "Left, Right" for a Compleo Duo – shown in the log,
  sessions, overview, CSV export and the dashboard card

## 1.3.0

- **Battery level (SoC):** read from the meter values when a station reports it (DC chargers,
  ISO 15118). Shown in the dashboard card, as a *Battery* entity in Home Assistant (created only once
  a station has reported it), per session on the *Sessions* page and in the CSV export.
  Plain AC charging (IEC 61851) does not transmit the battery level, so most wallboxes won't show it.
- OCPP 1.6 stations are asked for energy, power and SoC, falling back step by step if a measurand
  is rejected
- *Sessions* page: new filter by employee (also applied to the CSV export); shows the average
  energy per session when filtered

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
