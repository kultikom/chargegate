"""Import employees and RFID tags from Microsoft Entra ID.

Source: members of the group ENTRA_SYNC_GROUP_ID (nested groups included).
RFID UID: user attribute ENTRA_RFID_ATTRIBUTE, e.g. extensionAttribute10
(separate several tags with commas or spaces).

Rules:
- member of the group and account enabled    -> employee active
- removed from the group or account disabled -> employee deactivated (tags stop working)
- manually created tags are left alone, tags from Entra are reconciled
The app registration needs the application permissions User.Read.All and GroupMember.Read.All.
"""
from __future__ import annotations

import json
import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

import config
from db import Employee, Session, SyncState, Tag, normalize_uid, utcnow

log = logging.getLogger("entra")
GRAPH = "https://graph.microsoft.com/v1.0"


async def _token(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"https://login.microsoftonline.com/{config.ENTRA_TENANT_ID}/oauth2/v2.0/token",
        data={"client_id": config.ENTRA_CLIENT_ID, "client_secret": config.ENTRA_CLIENT_SECRET,
              "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]


async def fetch_users() -> list[dict]:
    select_ = "id,displayName,mail,userPrincipalName,accountEnabled,employeeId,onPremisesExtensionAttributes"
    url = (f"{GRAPH}/groups/{config.ENTRA_SYNC_GROUP_ID}/transitiveMembers/microsoft.graph.user"
           f"?$select={select_}&$top=999&$count=true")
    users: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Authorization": f"Bearer {await _token(client)}", "ConsistencyLevel": "eventual"}
        while url:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            users += data.get("value", [])
            url = data.get("@odata.nextLink")
    return users


def _uids(user: dict) -> list[str]:
    attr = config.ENTRA_RFID_ATTRIBUTE
    if attr.startswith("extensionAttribute"):
        raw = (user.get("onPremisesExtensionAttributes") or {}).get(attr)
    else:
        raw = user.get(attr)
    if not raw:
        return []
    return [normalize_uid(p) for p in re.split(r"[,;\s]+", str(raw)) if p.strip()]


async def apply_users(users: list[dict]) -> dict:
    """Reconcile the database with the given Entra users. Returns counters."""
    res = {"users": len(users), "created": 0, "updated": 0, "deactivated": 0,
           "tags_added": 0, "tags_removed": 0, "conflicts": []}
    async with Session() as s:
        emps = (await s.execute(select(Employee).options(selectinload(Employee.tags)))).scalars().all()
        by_entra = {e.entra_id: e for e in emps if e.entra_id}
        by_mail = {e.email.lower(): e for e in emps if e.email}
        all_tags = {t.uid: t for t in (await s.execute(select(Tag))).scalars().all()}
        seen: set[str] = set()

        for u in users:
            mail = (u.get("mail") or u.get("userPrincipalName") or "").lower() or None
            emp = by_entra.get(u["id"]) or (by_mail.get(mail) if mail else None)
            if emp is None:
                emp = Employee(name=u.get("displayName") or mail or u["id"], tags=[])
                s.add(emp)
                res["created"] += 1
            else:
                res["updated"] += 1
            emp.entra_id, emp.email, emp.source = u["id"], mail, "entra"
            emp.name = u.get("displayName") or emp.name
            emp.active = bool(u.get("accountEnabled", True))
            seen.add(u["id"])

            wanted = set(_uids(u))
            for t in list(emp.tags):
                if t.source == "entra" and t.uid not in wanted:
                    emp.tags.remove(t)
                    all_tags.pop(t.uid, None)
                    res["tags_removed"] += 1
            for uid in wanted:
                existing = all_tags.get(uid)
                if existing is None:
                    t = Tag(uid=uid, source="entra", label="Entra")
                    emp.tags.append(t)
                    all_tags[uid] = t
                    res["tags_added"] += 1
                elif existing not in emp.tags:
                    res["conflicts"].append(f"{uid} ({emp.name})")

        for e in emps:
            if e.source == "entra" and e.entra_id not in seen and e.active:
                e.active = False
                res["deactivated"] += 1
        await s.commit()
    res["conflicts"] = res["conflicts"][:10]
    return res


async def run_sync() -> dict:
    try:
        result = await apply_users(await fetch_users())
        ok = True
    except Exception as exc:  # noqa: BLE001
        log.exception("Entra sync failed")
        result, ok = {"error": str(exc)[:300]}, False
    async with Session() as s:
        st = await s.get(SyncState, 1) or SyncState(id=1)
        st.last_run, st.ok, st.message = utcnow(), ok, json.dumps(result)[:500]
        s.add(st)
        await s.commit()
    log.info("Entra sync: %s", result)
    return result
