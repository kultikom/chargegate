# Development & testing

```bash
cd chargegate/app
pip install -r requirements.txt
ADMIN_PASSWORD=test python main.py        # OCPP on :9000, web UI on :8080, SQLite in the current folder
```

## Station simulator

`simulator/sim.py` behaves like a charging station: boot, status, authorize, start, meter values,
stop. It also answers `SendLocalList`, `ClearCache` and `ChangeConfiguration`.

```bash
python simulator/sim.py --id TEST-01 --tag 04A2B3C4                    # OCPP 1.6
python simulator/sim.py --id TEST-02 --tag 04A2B3C4 --version 2.0.1     # OCPP 2.0.1, reports kWh
python simulator/sim.py --id TEST-01 --password secret --stay 20        # basic auth, wait for the tag list
python simulator/sim.py --id TEST-01 --kwh 11 --steps 10                # 11 kWh in 10 meter values
python simulator/sim.py --id DUO-01 --connector 2                       # second connector of a Duo
```

New stations are rejected until approved, so approve `TEST-01` in the UI first.

## Testing the Home Assistant app locally

```bash
mkdir -p /tmp/cg && echo '{"language": "auto"}' > /tmp/cg/options.json
cd chargegate
ADDON_DATA=/tmp/cg ADDON_APP_DIR=$PWD/app INGRESS_TRUSTED_IPS=127.0.0.1 python run.py
curl -H "X-Ingress-Path: /api/hassio_ingress/test" -H "X-Remote-User-Display-Name: Dev" http://127.0.0.1:8099/
```

## Project layout

```
repository.yaml          Home Assistant app repository
chargegate/              the app (HA app folder + standalone Dockerfile)
  config.yaml            HA app manifest – bump "version" for every release
  app/                   Python code: OCPP server, web UI, Entra sync
  translations/          HA option labels
simulator/               station simulator
docs/                    documentation
```

## MQTT locally

```bash
pip install amqtt && amqtt &                                 # small Python MQTT broker on :1883
MQTT_ENABLED=true MQTT_HOST=127.0.0.1 ADMIN_PASSWORD=test python main.py
```

## Translations

UI strings are English in the code; translations live in `chargegate/app/i18n.py`.
To add a language, add its code to `LANGUAGES` and a dictionary to `CATALOGS`.

## Releasing

1. Bump `version` in `chargegate/config.yaml` and `VERSION` in `chargegate/app/config.py`
2. Add an entry to `chargegate/CHANGELOG.md`
3. Push – Home Assistant shows the update and rebuilds the app on the device
