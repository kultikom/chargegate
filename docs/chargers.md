# Charging station setup

## General

| Setting | Value |
|---|---|
| Protocol | OCPP 1.6 JSON (1.6J) or OCPP 2.0.1 |
| Backend / central system URL | `ws://<server>:9000/ocpp/` |
| Charge box ID / identity | unique per station, e.g. `HQ-DUO-01` |
| Password (basic auth, security profile 1) | the password you set for this station in ChargeGate – or none |

Most stations append their ID to the URL themselves. If yours doesn't, use
`ws://<server>:9000/ocpp/<id>` – ChargeGate always takes the last path segment, so both work.

After the station connects for the first time it shows up under **Stations** as
*waiting for approval*. Approve it and assign a name and a site.

**Offline operation:** enable the station's local authorization list and authorization cache.
ChargeGate pushes all valid tags to the station after every change and clears the cache, so
charging keeps working if the server or the VPN is down, and blocked tags stop working at once.

**First station of a new model:** enable *Log OCPP messages* and watch the log while you present a
tag and start charging. Most issues (wrong ID, tag format, missing meter values) are visible there.

## Compleo ducto (Solo / Duo)

**Tested in production:** Compleo Duo SAM, Control Software 6.7.0. Setup notes are based on the
firmware 6.5 guide; menu names were identical.

Settings are made in the ducto web interface.

**Settings › Backend › Connection**

| Parameter | Value |
|---|---|
| Backend-URL | `ws://<server>:9000/ocpp/` |
| ChargeBoxIdentity | unique ID, e.g. `HQ-DUO-01` |
| AuthorizationKey | password from ChargeGate (basic auth), or empty |

**Settings › Backend**: *OCPP operating mode* = **Online**

**Settings › Backend › Charging authorization** – column *Backend + offline mode* of the Compleo guide:

| Parameter | Value |
|---|---|
| LocalAuthListEnabled | On |
| LocalAuthorizeOffline | On |
| LocalPreAuthorize | On |
| Cache | On |
| AuthorizeRemoteTxRequests | Off |
| AllowOfflineTXForUnknownId | Off |

**Additional features › ChargeForFree**: *Mode* = **Disabled**

**Settings › Connectors**: *Connector ID (OCPP)* 1 and 2 on a Duo. A Duo shows up as **one** station
with two connectors.

**Left or right?** OCPP only knows connector numbers, and the mapping is **not** fixed: on our first
Duo the side labelled *Left* in the ducto dashboard was OCPP connector **2**. Check each Duo once – plug
in a car and see which connector switches to *Charging* in ChargeGate (or compare *Settings ›
Connectors › Connector ID (OCPP)*), then enter the names in that order under *Stations › Edit ›
Charging point names*, e.g. `Right, Left`.

**Power readings:** the ducto only sends power (`Power.Active.Import`) after ChargeGate has set
`MeterValuesSampledData` – done automatically on every connection since ChargeGate 1.4.1. The new
setting may only apply from the next charging session; until then ChargeGate estimates the power
from the energy register.

Load management (master/slave) is independent of this – every ducto connects to ChargeGate itself.

## Alfen Eve Single Pro-line (e.g. 904460027) and Pro-line DE (e.g. 904460127)

**Tested in production:** Alfen Eve Single Pro-line, model **NG910-60027**, firmware **5.5.1-4099**
(reports itself as vendor `Alfen BV`). The Pro-line DE variant has not been tested yet.

Configured with the **ACE Service Installer** (Windows; an installer account from Alfen is required).
Menu names vary between firmware and installer versions.

| Setting | Value |
|---|---|
| Protocol | OCPP 1.6 (JSON) |
| Backend URL | `ws://<server>:9000/ocpp/` |
| Charge point ID | unique, by default `ALFEN_<serial number>` |
| Security profile | 0 (no password) or 1 (basic auth with the password from ChargeGate) |
| Authorization | via OCPP, local list allowed (for offline operation) |

Disable the network connection you don't use (LAN or cellular) and restart the station afterwards.

**Offline queue:** an Alfen that has been running without a backend keeps its sessions and sends all
of them – possibly years back – right after connecting to ChargeGate. They are stored with their real
date and marked *sent afterwards*; delete them under *Sessions* (filter by station and period, or
*Clean up*) if you don't need them.

The **Pro-line DE** is the variant compliant with German calibration law (Eichrecht). It additionally
sends signed meter values (`SignedData`). ChargeGate ignores these and uses the regular energy
register – fine for internal reporting. Compliant billing would require storing the signed records.

## Tag UIDs

ChargeGate normalizes UIDs (upper case, hex only), so `04:a2:b3:c4` and `04A2B3C4` are the same.
Some readers report the UID in reversed byte order; ChargeGate recognizes this and notes it in the log.
Easiest onboarding: hold the tag against any station and assign it under *Unknown tags*.
