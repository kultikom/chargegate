# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""License check with KultiLic keys (offline, Ed25519).

Rules (see LICENSE, additional use grant):
- without a key: 2 charging points for free
- with a valid key: as many charging points as licensed (limit "charging_points")
- over the limit, existing charging points keep working: charging points are licensed in the order
  their stations were approved; stations approved later, beyond the limit, are blocked
  (tags rejected, empty local list) and marked in the UI
- subscriptions: warning 30 days before the end, 14 days grace afterwards
- installations that already had more than 2 charging points when licensing was introduced get a
  transition period of 30 days to enter a key – nothing is blocked during that time
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db import AppSetting, Session, Station, utcnow
from kultilic_verify import check

log = logging.getLogger("chargegate.license")

PRODUCT = "chargegate"
FREE_CHARGING_POINTS = 2
TRANSITION_DAYS = 30
GRACE_DAYS = 14      # kultilic_verify default
# Public key(s) of the product "chargegate" in KultiLic ({key id: base64url raw Ed25519 key}).
# Keep every key that was ever used, so older licenses keep verifying after a key rotation.
PUBLIC_KEYS = {"4daf1b7e": "WjrICVFKc73W21goB200qzKP8e1VMSodxLnA50qe1CQ"}


@dataclass
class LicenseState:
    key: str | None = None
    status: str = "none"                 # none | valid | expiring | grace | expired | not_yet_valid | invalid
    error: str | None = None
    customer: str | None = None
    license_id: str | None = None
    license_type: str | None = None
    valid_until: date | None = None
    days_left: int | None = None
    limit: int = FREE_CHARGING_POINTS
    used: int = 0
    transition_until: date | None = None
    stations: list[dict] = field(default_factory=list)     # [{id, name, points, licensed}]
    blocked: set[str] = field(default_factory=set)

    @property
    def grace_until(self) -> date | None:
        return self.valid_until + timedelta(days=GRACE_DAYS) if self.valid_until else None

    @property
    def in_transition(self) -> bool:
        return bool(self.transition_until and date.today() <= self.transition_until)

    @property
    def over_limit(self) -> bool:
        return self.used > self.limit

    @property
    def banner(self) -> tuple[str, str] | None:
        """(kind, message key) for the banner on every page, or None."""
        if self.in_transition and self.over_limit:
            return "warn", "transition"
        if self.status == "invalid":
            return "err", "invalid"
        if self.blocked:
            return "err", "blocked"
        if self.status == "grace":
            return "err", "grace"
        if self.status == "expired":
            return "err", "expired"
        if self.status == "expiring":
            return "warn", "expiring"
        return None


_state = LicenseState()
_computed = 0.0


def current() -> LicenseState:
    """Last computed state (sync, for templates)."""
    return _state


async def get_setting(key: str) -> str | None:
    async with Session() as s:
        row = await s.get(AppSetting, key)
        return row.value if row else None


async def set_setting(key: str, value: str | None) -> None:
    async with Session() as s:
        row = await s.get(AppSetting, key)
        if value is None:
            if row:
                await s.delete(row)
        elif row:
            row.value = value
        else:
            s.add(AppSetting(key=key, value=value))
        await s.commit()


async def installation_id() -> str:
    iid = await get_setting("installation_id")
    if not iid:
        iid = secrets.token_hex(8)
        await set_setting("installation_id", iid)
    return iid


def points_of(st: Station) -> int:
    """Charging points of a station = its connectors (connector 0 is the station itself)."""
    return max(1, len([c for c in st.connectors if c.connector_id and c.connector_id > 0]))


async def refresh(quiet: bool = False) -> LicenseState:
    """Recompute the license state (after changes, on start and periodically)."""
    global _state, _computed
    st = LicenseState(key=await get_setting("license_key"))
    iid = await installation_id()
    if st.key:
        r = check(st.key, PUBLIC_KEYS, product=PRODUCT, installation_id=iid)
        st.status, st.error, st.days_left = r.status, r.error, r.days_left
        st.customer, st.license_id, st.valid_until = r.customer, r.license_id, r.valid_until
        st.license_type = r.claims.get("typ")
        st.limit = r.limit("charging_points", default=FREE_CHARGING_POINTS)
    tu = await get_setting("transition_until")
    st.transition_until = date.fromisoformat(tu) if tu else None

    async with Session() as s:
        stations = (await s.execute(select(Station).options(selectinload(Station.connectors))
                                    .where(Station.approved))).scalars().all()
    stations = sorted(stations, key=lambda x: (x.approved_at or x.first_seen, x.first_seen, x.id))
    total = 0
    for x in stations:
        p = points_of(x)
        total += p
        licensed = total <= st.limit or st.in_transition
        st.stations.append({"id": x.id, "name": x.name, "points": p, "licensed": licensed})
        if not licensed:
            st.blocked.add(x.id)
    st.used = total
    if st.blocked and st.blocked != _state.blocked and not quiet:
        log.warning("License limit %s charging points reached – blocked: %s", st.limit, ", ".join(sorted(st.blocked)))
    _state, _computed = st, time.monotonic()
    return st


async def station_licensed(station_id: str) -> bool:
    if time.monotonic() - _computed > 60:
        await refresh()
    return station_id not in _state.blocked


async def start() -> None:
    """On start: installation ID, transition period for existing larger installations."""
    await installation_id()
    if await get_setting("licensing_since") is None:
        await set_setting("licensing_since", utcnow().date().isoformat())
        st = await refresh(quiet=True)
        if st.used > FREE_CHARGING_POINTS and not st.key:
            until = date.today() + timedelta(days=TRANSITION_DAYS)
            await set_setting("transition_until", until.isoformat())
            log.warning("%s charging points in use, free are %s: please enter a license key by %s",
                        st.used, FREE_CHARGING_POINTS, until)
    await refresh()


async def set_key(key: str | None) -> LicenseState:
    from kultilic_verify import normalize
    await set_setting("license_key", normalize(key) if key else None)
    return await refresh()
