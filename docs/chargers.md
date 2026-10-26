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

## Compleo ducto (Solo / Duo), firmware 6.5

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

**Left or right?** OCPP only knows connector numbers. Plug in a car or check the ducto web interface
to see which side is connector 1, then enter names like `Left, Right` under *Stations › Edit ›
Charging point names* – they appear in the log, sessions and the dashboard.

Load management (master/slave) is independent of this – every ducto connects to ChargeGate itself.

## Alfen Eve Single Pro-line (e.g. 904460027) and Pro-line DE (e.g. 904460127)

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

The **Pro-line DE** is the variant compliant with German calibration law (Eichrecht). It additionally
sends signed meter values (`SignedData`). ChargeGate ignores these and uses the regular energy
register – fine for internal reporting. Compliant billing would require storing the signed records.

## Tag UIDs

ChargeGate normalizes UIDs (upper case, hex only), so `04:a2:b3:c4` and `04A2B3C4` are the same.
Some readers report the UID in reversed byte order; ChargeGate recognizes this and notes it in the log.
Easiest onboarding: hold the tag against any station and assign it under *Unknown tags*.
