# Security

ChargeGate is built for a company network (LAN/VPN). It still assumes that other devices on that
network may not be trustworthy.

## What you should do

- **Station passwords:** give every station an OCPP basic-auth password (*Stations › Edit*) and enter
  the same password in the station. Without one, any device on the network could connect with that
  station's ID: replace the real station, report fake sessions or check tags. The stations page marks
  approved stations without a password.
- **Keep station approval on** (`require_station_approval`), so unknown devices can't connect.
- **Web UI:** in Home Assistant use the side panel (ingress). Only open port 8099 if you need direct
  access, and then with a long admin password. Standalone: set `ADMIN_PASSWORD` (at least 10
  characters) or use Entra ID; otherwise a random password is generated and shown in the log.
- **OCPP and web ports** belong in the company network or a VPN, not on the internet. OCPP 1.6 over
  `ws://` is unencrypted.
- **MQTT:** use a broker with user accounts (the Mosquitto app does that); whoever can publish to the
  TeslaMate topics can change the battery levels ChargeGate shows.

## What ChargeGate does

| Risk | Protection |
|---|---|
| Guessing the admin password | 5 wrong passwords per address within 10 min lock the login (1 min, doubling up to 30 min); constant-time comparison; new session on login |
| Forged sessions | session cookie signed with a random key (generated if `SECRET_KEY` is not set), `SameSite=Lax` |
| Cross-site requests (CSRF) | form posts from other sites are rejected (browser header `Sec-Fetch-Site`) – also via Home Assistant ingress |
| Script injection (XSS) | all output is escaped, also texts in confirmation dialogs; Content-Security-Policy, `X-Content-Type-Options`, `Referrer-Policy` |
| Clickjacking | may only be framed by the same origin (Home Assistant ingress) |
| Guessing PINs/tags via a station | 20 unknown tags per station within 10 min refuse that station's checks (5 min, doubling up to 1 h); visible in the log |
| Looking up who owns a tag | a station only gets the name of a tag it has just accepted |
| Guessing station passwords | 10 failures per address within 10 min block it (5 min, doubling up to 1 h) |
| Flooding with fake stations | only sensible charge box IDs (letters, digits, `._:@~-`, max. 64), at most 50 stations waiting for approval |
| Oversized requests | web requests up to 1 MB, OCPP messages up to 1 MB |
| Fake cars via MQTT | car IDs checked, at most 200 cars, all values escaped |
| Formulas in the CSV export | cells starting with `=`, `+`, `-`, `@` are neutralised |
