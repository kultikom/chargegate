"""Minimal translation layer. English is the source language, German the first translation.

To add a language: add its code to LANGUAGES and a dictionary to CATALOGS.
"""
from __future__ import annotations

from contextvars import ContextVar
from http.cookies import SimpleCookie

import config

LANGUAGES = ("en", "de")
_lang: ContextVar[str] = ContextVar("lang", default="en")


def set_language(code: str) -> None:
    _lang.set(code if code in LANGUAGES else "en")


def current() -> str:
    return _lang.get()


def pick_language(cookie_header: str, accept_language: str) -> str:
    """Cookie (language switch in the footer) > configured language > browser language."""
    try:
        c = SimpleCookie(cookie_header)
        if "lang" in c and c["lang"].value in LANGUAGES:
            return c["lang"].value
    except Exception:  # noqa: BLE001
        pass
    if config.LANGUAGE in LANGUAGES:
        return config.LANGUAGE
    for part in accept_language.split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGUAGES:
            return code
    return "en"


_EN = {"Superseded": "no stop received, ended by the next session","phase_offline": "Offline", "phase_free": "Free", "phase_connected": "Connected",
       "phase_charging": "Charging", "phase_done": "Done", "phase_paused": "Paused",
       "phase_fault": "Fault", "phase_unavailable": "Unavailable", "phase_reserved": "Reserved"}


def t(msg: str, **kw) -> str:
    text = CATALOGS.get(current(), {}).get(msg) or _EN.get(msg, msg)
    return text.format(**kw) if kw else text


def number(value: float, digits: int) -> str:
    s = f"{value:.{digits}f}"
    return s.replace(".", ",") if current() == "de" else s


_DATE = {
    "en": {"full": "%Y-%m-%d %H:%M", "short": "%m-%d %H:%M", "time": "%H:%M", "seconds": "%Y-%m-%d %H:%M:%S", "date": "%Y-%m-%d"},
    "de": {"full": "%d.%m.%Y %H:%M", "short": "%d.%m. %H:%M", "time": "%H:%M", "seconds": "%d.%m.%Y %H:%M:%S", "date": "%d.%m.%Y"},
}


def date_format(kind: str) -> str:
    return _DATE[current()].get(kind, kind)


RESULTS = {"Accepted": "accepted", "Blocked": "blocked", "Invalid": "unknown"}
REASONS = {
    "unknown_tag": "unknown tag",
    "tag_blocked": "tag blocked",
    "employee_inactive": "employee deactivated",
    "reversed_byte_order": "UID matched in reversed byte order",
}


def result_label(result: str | None) -> str:
    return t(RESULTS.get(result or "", result or ""))


def reason_label(reason: str | None) -> str:
    return t(REASONS.get(reason, reason)) if reason else ""


DE = {
    # navigation & general
    "Overview": "Übersicht", "Stations": "Stationen", "Employees & tags": "Mitarbeiter & Chips",
    "Sessions": "Ladevorgänge", "Log": "Protokoll", "Sign out": "Abmelden",
    "Add": "Hinzufügen", "Save": "Speichern", "Delete": "Löschen", "delete": "löschen",
    "Remove": "Entfernen", "Edit": "Bearbeiten", "Search": "Suchen", "Show": "Anzeigen",
    "Name": "Name", "Email": "E-Mail", "optional": "optional", "all": "alle",
    "ok": "ok", "error": "Fehler", "online": "online", "offline": "offline",
    "never": "nie", "just now": "gerade eben", "{n} min ago": "vor {n} Min.",
    "{n} h ago": "vor {n} Std.", "{n} days ago": "vor {n} Tagen",
    "manual": "manuell", "entra": "Entra",
    # login
    "RFID access for your charging stations": "RFID-Freigabe für eure Ladestationen",
    "Sign in with Microsoft": "Mit Microsoft anmelden", "Admin password": "Admin-Passwort",
    "Sign in": "Anmelden", "Wrong password": "Passwort falsch",
    "Local login – Entra ID is not configured.": "Lokaler Login – Entra ID ist nicht konfiguriert.",
    "Direct access is disabled. Please open the interface from the Home Assistant sidebar.":
        "Der direkte Zugriff ist deaktiviert. Bitte die Oberfläche über die Home-Assistant-Seitenleiste öffnen.",
    "{email} is not an authorized admin.": "{email} ist nicht als Admin freigeschaltet.",
    # overview
    "{online} of {total} stations online · {running} sessions running":
        "{online} von {total} Stationen online · {running} Ladevorgänge laufen",
    "{n} new station(s) connected and are waiting for approval.":
        "{n} neue Station(en) haben sich gemeldet und warten auf Freigabe.",
    "Review now →": "Jetzt prüfen →",
    "No approved stations yet. Point a station to this address – it will then appear under “Stations”.":
        "Noch keine Stationen freigegeben. Trag diese Adresse in der Wallbox ein – sie erscheint dann unter „Stationen“.",
    "Copy": "Kopieren", "Copied": "Kopiert",
    "The station appends its ChargeBox ID itself.": "Die Wallbox hängt ihre ChargeBox-ID selbst an.",
    "The OCPP port is disabled in the app's network settings – stations cannot connect.":
        "Der OCPP-Port ist in den Netzwerk-Einstellungen der App deaktiviert – Wallboxen können sich nicht verbinden.",
    "No site": "Ohne Standort", "no status yet": "noch kein Status", "last seen": "zuletzt gesehen",
    "Running sessions": "Laufende Ladevorgänge", "Employee": "Mitarbeiter", "Station": "Station",
    "Since": "Seit", "since": "seit",
    "phase_offline": "Offline", "phase_free": "Frei", "phase_connected": "Verbunden",
    "phase_charging": "Lädt", "phase_done": "Fertig", "phase_paused": "Pausiert",
    "phase_fault": "Störung", "phase_unavailable": "Nicht verfügbar", "phase_reserved": "Reserviert", "So far": "Bisher", "Nobody is charging right now.": "Gerade lädt niemand.",
    "Recent authorizations": "Letzte Anmeldungen", "No tags read yet.": "Noch keine Chips gelesen.",
    # stations
    "OCPP address for your stations:": "OCPP-Adresse für die Wallboxen:",
    "Name / site": "Name / Standort", "Device": "Gerät", "Status": "Status", "Last seen": "Zuletzt",
    "no site": "kein Standort", "waiting for approval": "wartet auf Freigabe",
    "Basic auth enabled": "Basic Auth aktiv", "Tag list:": "Chip-Liste:",
    "Approve": "Freigeben", "Site": "Standort", "e.g. North car park 1": "z. B. Parkplatz Nord 1",
    "New basic auth password": "Neues Basic-Auth-Passwort", "unchanged": "unverändert",
    "approved": "freigegeben", "remove password": "Passwort entfernen",
    "Send tag list now": "Chip-Liste jetzt senden",
    "Delete station? Its sessions will be deleted as well.":
        "Station löschen? Ihre Ladevorgänge werden mitgelöscht.",
    "No stations yet. Point a station to this server or add one manually below.":
        "Noch keine Station. Wallbox auf diesen Server zeigen lassen oder unten manuell anlegen.",
    "Add station manually": "Station manuell anlegen", "as configured in the station": "wie in der Wallbox",
    "Basic auth password": "Basic-Auth-Passwort", "Sites": "Standorte", "Delete site?": "Standort löschen?",
    "No sites yet.": "Noch keine Standorte.", "e.g. Head office": "z. B. Zentrale",
    "Station {id} saved": "Station {id} gespeichert", "Station {id} deleted": "Station {id} gelöscht",
    "Tag list to {id}: {status}": "Chip-Liste an {id}: {status}",
    "Site {name} added": "Standort {name} angelegt", "Site already exists": "Standort existiert bereits",
    "ok ({n} tags)": "ok ({n} Chips)", "error: {msg}": "Fehler: {msg}",
    # employees
    "An active tag of an active employee works at every site.":
        "Ein aktiver Chip eines aktiven Mitarbeiters gilt an allen Standorten.",
    "Unknown tags (last 30 days)": "Unbekannte Chips (letzte 30 Tage)",
    "Simply hold a new tag against any station – it shows up here and can be assigned right away.":
        "Neuen Chip einfach an eine Wallbox halten – er erscheint hier und kann direkt zugeordnet werden.",
    "Attempts": "Versuche", "Assign": "Zuordnen", "– new employee –": "– neuer Mitarbeiter –",
    "Name (if new)": "Name (falls neu)", "Search by name, email or tag UID": "Suche nach Name, E-Mail oder Chip-UID",
    "Tags": "Chips", "Tag": "Chip", "Source": "Quelle", "deactivated": "deaktiviert",
    "block": "sperren", "unblock": "entsperren", "Delete tag?": "Chip löschen?", "no tag": "kein Chip",
    "+ Tag": "+ Chip", "UID, e.g. 04A2B3C4D5": "UID, z. B. 04A2B3C4D5", "Label (optional)": "Bezeichnung (optional)",
    "Deactivate": "Deaktivieren", "Activate": "Aktivieren", "Delete employee?": "Mitarbeiter löschen?",
    "No employees found.": "Keine Mitarbeiter gefunden.", "Add employee manually": "Mitarbeiter manuell anlegen",
    "Tag UID": "Chip-UID",
    "Employees from Entra are maintained in Entra ID": "Entra-Mitarbeiter werden in Entra ID gepflegt",
    "Name must not be empty": "Der Name darf nicht leer sein", "{name} saved": "{name} gespeichert",
    "Tag labels": "Chip-Bezeichnungen",
    "Employees and tags are imported from the Entra group. Tag UIDs are read from the attribute":
        "Mitarbeiter und Chips werden aus der Entra-Gruppe übernommen. Chip-UIDs stehen im Attribut",
    "Last run": "Letzter Lauf", "Sync now": "Jetzt synchronisieren",
    "Not configured. Add the Entra settings to import employees from a group automatically and block them when they leave.":
        "Nicht konfiguriert. Mit den Entra-Einstellungen werden Mitarbeiter automatisch aus einer Gruppe übernommen und beim Austritt gesperrt.",
    "{name} added": "{name} angelegt",
    "This tag is already assigned to another employee": "Dieser Chip ist bereits einem anderen Mitarbeiter zugeordnet",
    "This tag is already assigned": "Dieser Chip ist bereits zugeordnet",
    "Note: employees from Entra are overwritten by the next sync":
        "Hinweis: Entra-Mitarbeiter werden beim nächsten Sync überschrieben",
    "Please select an employee or enter a name": "Bitte Mitarbeiter wählen oder Namen eingeben",
    "Employee not found": "Mitarbeiter nicht gefunden", "Tag {uid} → {name}": "Chip {uid} → {name}",
    "Entra sync is not configured": "Entra-Sync ist nicht konfiguriert",
    "{users} users: {created} new, {updated} updated, {deactivated} deactivated; tags +{tags_added}/-{tags_removed}":
        "{users} Benutzer: {created} neu, {updated} aktualisiert, {deactivated} deaktiviert; Chips +{tags_added}/-{tags_removed}",
    "conflicts (tag already belongs to someone else): {list}":
        "Konflikte (Chip gehört schon jemand anderem): {list}",
    # sessions
    "Month": "Monat", "CSV export": "CSV-Export", "Total energy": "Energie gesamt",
    "By employee": "Nach Mitarbeiter", "Start": "Start", "End": "Ende", "Energy": "Energie",
    "Reason": "Grund", "running": "läuft", "No sessions in this period.": "Keine Ladevorgänge in diesem Zeitraum.",
    "Connector": "Anschluss", "Meter start (Wh)": "Zähler Start (Wh)", "Meter end (Wh)": "Zähler Ende (Wh)",
    "Stop reason": "Stoppgrund", "kWh": "kWh", "Battery": "Akkustand", "Period": "Zeitraum", "Reset": "Zurücksetzen",
    "{n} of {total} employees match “{q}”": "{n} von {total} Mitarbeitern passen zu „{q}“",
    "Energy dashboard": "Energie-Dashboard",
    "Counts in the Energy dashboard of this Home Assistant": "Zählt im Energie-Dashboard dieses Home Assistant",
    "Tick the sites whose charging is part of this building's consumption – only their stations can be added to the Energy dashboard of this Home Assistant.":
        "Haken bei den Standorten, deren Ladestrom zum Verbrauch dieses Gebäudes gehört – nur deren Stationen lassen sich ins Energie-Dashboard dieses Home Assistant aufnehmen.",
    "{name}: energy counts in Home Assistant": "{name}: Energie zählt in Home Assistant",
    "{name}: energy no longer counts in Home Assistant": "{name}: Energie zählt nicht mehr in Home Assistant", "Superseded": "ohne Stopp, beendet durch Folgevorgang",
    "sent afterwards": "nachgemeldet", "Sent by the station afterwards on {date}": "Von der Wallbox nachgemeldet am {date}",
    "Delete selected": "Ausgewählte löschen", "Delete all {n} shown": "Alle {n} angezeigten löschen",
    "Delete the selected sessions?": "Ausgewählte Ladevorgänge löschen?",
    "Delete all {n} sessions shown with this filter? This cannot be undone.":
        "Alle {n} Ladevorgänge dieses Filters löschen? Das kann nicht rückgängig gemacht werden.",
    "select all": "alle auswählen", "{n} selected": "{n} ausgewählt", "No sessions selected": "Keine Ladevorgänge ausgewählt",
    "Sessions deleted: {n}": "Ladevorgänge gelöscht: {n}", "Clean up": "Aufräumen",
    "Delete everything before": "Alles löschen vor dem", "finished sessions": "abgeschlossene Ladevorgänge",
    "log entries": "Protokolleinträge", "Please enter a date": "Bitte ein Datum angeben",
    "Delete everything before this date? This cannot be undone.":
        "Alles vor diesem Datum löschen? Das kann nicht rückgängig gemacht werden.",
    "Deleted before {date} – sessions: {tx}, log entries: {log}":
        "Vor dem {date} gelöscht – Ladevorgänge: {tx}, Protokolleinträge: {log}",
    "Tip: a backup of the database is part of every Home Assistant backup.":
        "Tipp: Die Datenbank ist in jedem Home-Assistant-Backup enthalten.", "Charging point": "Ladepunkt",
    "Charging point names": "Ladepunkt-Namen", "e.g. Left, Right": "z. B. Links, Rechts",
    "Comma-separated, in the order of the connector numbers 1, 2, …":
        "Mit Komma getrennt, in der Reihenfolge der Anschlussnummern 1, 2, …", "Average per session": "Ø pro Ladevorgang",
    "SoC start (%)": "Akkustand Start (%)", "SoC end (%)": "Akkustand Ende (%)",
    # log
    "Every tag check at a station (latest 300)": "Jede Chip-Prüfung an einer Wallbox (letzte 300)",
    "all results": "alle Ergebnisse", "Time": "Zeit", "Result": "Ergebnis", "Note": "Hinweis",
    "No entries yet.": "Noch keine Einträge.",
    "accepted": "akzeptiert", "blocked": "gesperrt", "unknown": "unbekannt",
    "unknown tag": "Chip unbekannt", "tag blocked": "Chip gesperrt",
    "employee deactivated": "Mitarbeiter deaktiviert",
    "UID matched in reversed byte order": "UID in umgekehrter Byte-Reihenfolge erkannt",
}

CATALOGS = {"de": DE}
