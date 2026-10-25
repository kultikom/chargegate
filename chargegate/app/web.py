"""Web UI for admins (own port, internal/VPN only – or via Home Assistant ingress)."""
from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

import config
import core
import entra_sync
import i18n
from db import (AuthEvent, Employee, Session, Site, Station, SyncState, Tag,
                Transaction, hash_password, normalize_uid, utcnow)
from i18n import t as _

log = logging.getLogger("web")
TZ = ZoneInfo(config.TIMEZONE)
BASE = __file__.rsplit("/", 1)[0]
templates = Jinja2Templates(directory=f"{BASE}/templates")


# --- Formatting -------------------------------------------------------------------------

def local(dt: datetime | None, fmt: str = "full") -> str:
    if dt is None:
        return "–"
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).strftime(i18n.date_format(fmt))


def ago(dt: datetime | None) -> str:
    if dt is None:
        return _("never")
    sec = int((utcnow() - dt).total_seconds())
    if sec < 90:
        return _("just now")
    if sec < 3600:
        return _("{n} min ago", n=sec // 60)
    if sec < 86400:
        return _("{n} h ago", n=sec // 3600)
    return _("{n} days ago", n=sec // 86400)


def kwh(v: float | None) -> str:
    return "–" if v is None else i18n.number(v, 2) + " kWh"


def list_status(value: str | None) -> str:
    if not value:
        return ""
    kind, _sep, detail = value.partition(":")
    if kind == "ok":
        return _("ok ({n} tags)", n=detail)
    if kind == "error":
        return _("error: {msg}", msg=detail)
    return _(value)


def sync_summary(message: str | None) -> str:
    try:
        r = json.loads(message or "{}")
    except ValueError:
        return message or ""
    if "error" in r:
        return _("error: {msg}", msg=r["error"])
    text = _("{users} users: {created} new, {updated} updated, {deactivated} deactivated; "
             "tags +{tags_added}/-{tags_removed}", **{k: v for k, v in r.items() if k != "conflicts"})
    if r.get("conflicts"):
        text += "; " + _("conflicts (tag already belongs to someone else): {list}",
                         list=", ".join(r["conflicts"]))
    return text


templates.env.filters.update(local=local, ago=ago, kwh=kwh, list_status=list_status,
                             sync_summary=sync_summary, result=i18n.result_label,
                             reason=i18n.reason_label)
templates.env.globals.update(_=_, version=config.VERSION, ocpp_port=config.OCPP_PORT,
                             entra_login=config.ENTRA_LOGIN_ENABLED,
                             entra_sync=config.ENTRA_SYNC_ENABLED,
                             rfid_attr=config.ENTRA_RFID_ATTRIBUTE,
                             local_login=bool(config.ADMIN_PASSWORD))


# --- Login --------------------------------------------------------------------------------

oauth = None
if config.ENTRA_LOGIN_ENABLED:
    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    oauth.register(
        "entra",
        client_id=config.ENTRA_CLIENT_ID,
        client_secret=config.ENTRA_CLIENT_SECRET,
        server_metadata_url=(f"https://login.microsoftonline.com/{config.ENTRA_TENANT_ID}"
                             "/v2.0/.well-known/openid-configuration"),
        client_kwargs={"scope": "openid email profile"},
    )


class LoginRequired(Exception):
    pass


# --- Request context: Home Assistant ingress + language -----------------------------------
# As a Home Assistant app the UI runs behind the HA proxy under a path prefix.
# HA has already authenticated the user and passes the name in a header.

_base: ContextVar[str] = ContextVar("base", default="")


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            client = (scope.get("client") or ("", 0))[0]
            prefix = headers.get("x-ingress-path", "").rstrip("/")
            if prefix and client in config.INGRESS_TRUSTED_IPS:
                scope["ingress_user"] = (headers.get("x-remote-user-display-name")
                                         or headers.get("x-remote-user-name") or "Home Assistant")
                _base.set(prefix)
            else:
                _base.set("")
            i18n.set_language(i18n.pick_language(headers.get("cookie", ""),
                                                 headers.get("accept-language", "")))
        await self.app(scope, receive, send)


def current_user(request: Request) -> str | None:
    return request.scope.get("ingress_user") or request.session.get("user")


def admin(request: Request) -> str:
    user = current_user(request)
    if not user:
        raise LoginRequired()
    return user


def flash(request: Request, msg: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append([kind, msg])


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.update(request=request, user=current_user(request), base=_base.get(),
               lang=i18n.current(), via_ingress="ingress_user" in request.scope,
               flashes=request.session.pop("flash", []), path=request.url.path)
    return templates.TemplateResponse(request, name, ctx)


def back(url: str) -> RedirectResponse:
    return RedirectResponse(_base.get() + url, status_code=303)


# --- App ------------------------------------------------------------------------------------

async def _sync_loop():
    while True:
        await entra_sync.run_sync()
        core.schedule_push_all(delay=1)
        await asyncio.sleep(config.ENTRA_SYNC_INTERVAL_MIN * 60)


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_sync_loop()) if config.ENTRA_SYNC_ENABLED else None
    yield
    if task:
        task.cancel()


web_app = FastAPI(title="ChargeGate", lifespan=lifespan, docs_url=None, redoc_url=None)
web_app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, same_site="lax",
                       max_age=12 * 3600)
web_app.add_middleware(RequestContextMiddleware)
web_app.mount("/static", StaticFiles(directory=f"{BASE}/static"), name="static")


@web_app.exception_handler(LoginRequired)
async def _login_redirect(request, exc):
    return back("/login")


@web_app.get("/lang/{code}")
async def set_lang(code: str):
    resp = back("/")
    if code in i18n.LANGUAGES:
        resp.set_cookie("lang", code, max_age=365 * 86400, samesite="lax")
    return resp


@web_app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render(request, "login.html")


@web_app.post("/login")
async def login_local(request: Request, password: str = Form(...)):
    if config.ENTRA_LOGIN_ENABLED:
        raise HTTPException(404)
    if not config.ADMIN_PASSWORD or password != config.ADMIN_PASSWORD:
        flash(request, _("Wrong password"), "err")
        return back("/login")
    request.session["user"] = "admin"
    return back("/")


@web_app.get("/auth/login")
async def auth_login(request: Request):
    redirect = config.ENTRA_REDIRECT_URI or str(request.url_for("auth_callback"))
    return await oauth.entra.authorize_redirect(request, redirect)


@web_app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.entra.authorize_access_token(request)
    info = token.get("userinfo") or {}
    email = (info.get("preferred_username") or info.get("email") or "").lower()
    groups = info.get("groups") or []
    allowed = (email in config.ADMIN_EMAILS) or (config.ADMIN_GROUP_ID and config.ADMIN_GROUP_ID in groups)
    if not allowed:
        log.warning("Login denied for %s", email)
        flash(request, _("{email} is not an authorized admin.", email=email), "err")
        return back("/login")
    request.session["user"] = email
    return back("/")


@web_app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return back("/login")


# --- Overview ---------------------------------------------------------------------------------

@web_app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(admin)):
    async with Session() as s:
        stations = (await s.execute(select(Station).where(Station.approved)
                                    .options(selectinload(Station.site), selectinload(Station.connectors))
                                    .order_by(Station.site_id, Station.id))).scalars().all()
        pending = (await s.execute(select(func.count()).select_from(Station)
                                   .where(Station.approved.is_(False)))).scalar()
        running = (await s.execute(select(Transaction).where(Transaction.stopped_at.is_(None))
                                   .options(selectinload(Transaction.employee),
                                            selectinload(Transaction.station))
                                   .order_by(Transaction.started_at.desc()))).scalars().all()
        events = (await s.execute(select(AuthEvent).options(selectinload(AuthEvent.employee))
                                  .order_by(AuthEvent.ts.desc()).limit(12))).scalars().all()
    return render(request, "index.html", stations=stations, pending=pending, running=running,
                  events=events, online=set(core.connected), ocpp_url=ocpp_url(request))


# --- Stations & sites -------------------------------------------------------------------------

def ocpp_url(request: Request) -> str | None:
    """The ready-to-use URL for the stations, or None if it can't be determined."""
    if config.PUBLIC_OCPP_URL:
        return config.PUBLIC_OCPP_URL
    if "ingress_user" in request.scope or not request.url.hostname:
        return None  # behind the HA proxy the request host says nothing about the OCPP host
    return f"ws://{request.url.hostname}:{config.OCPP_PORT}/ocpp/"


@web_app.get("/stations", response_class=HTMLResponse)
async def stations_page(request: Request, user=Depends(admin)):
    async with Session() as s:
        stations = (await s.execute(select(Station).options(selectinload(Station.site))
                                    .order_by(Station.approved, Station.id))).scalars().all()
        sites = (await s.execute(select(Site).order_by(Site.name))).scalars().all()
    return render(request, "stations.html", stations=stations, sites=sites, online=set(core.connected),
                  ocpp_url=ocpp_url(request))


@web_app.post("/stations/save")
async def station_save(request: Request, user=Depends(admin), id: str = Form(...),
                       name: str = Form(""), site_id: str = Form(""), password: str = Form(""),
                       clear_password: str = Form(""), approved: str = Form("")):
    sid = id.strip()
    async with Session() as s:
        st = await s.get(Station, sid) or Station(id=sid)
        st.name = name.strip() or None
        st.site_id = int(site_id) if site_id else None
        st.approved = bool(approved)
        if password:
            st.password_hash = hash_password(password)
        elif clear_password:
            st.password_hash = None
        s.add(st)
        await s.commit()
    core.notify(sid)
    flash(request, _("Station {id} saved", id=sid))
    return back("/stations")


@web_app.post("/stations/{sid}/delete")
async def station_delete(request: Request, sid: str, user=Depends(admin)):
    async with Session() as s:
        if st := await s.get(Station, sid):
            await s.delete(st)
            await s.commit()
    core.notify(sid)
    flash(request, _("Station {id} deleted", id=sid))
    return back("/stations")


@web_app.post("/stations/{sid}/push")
async def station_push(request: Request, sid: str, user=Depends(admin)):
    status = await core.push_local_list(sid)
    flash(request, _("Tag list to {id}: {status}", id=sid, status=list_status(status)),
          "ok" if status.startswith("ok") else "err")
    return back("/stations")


@web_app.post("/sites/add")
async def site_add(request: Request, user=Depends(admin), name: str = Form(...)):
    async with Session() as s:
        s.add(Site(name=name.strip()))
        try:
            await s.commit()
            flash(request, _("Site {name} added", name=name.strip()))
        except IntegrityError:
            flash(request, _("Site already exists"), "err")
    return back("/stations")


@web_app.post("/sites/{site_id}/delete")
async def site_delete(request: Request, site_id: int, user=Depends(admin)):
    async with Session() as s:
        if site := await s.get(Site, site_id):
            await s.delete(site)
            await s.commit()
    core.notify_all()
    return back("/stations")


# --- Employees & tags ---------------------------------------------------------------------------

@web_app.get("/employees", response_class=HTMLResponse)
async def employees_page(request: Request, user=Depends(admin), q: str = ""):
    async with Session() as s:
        stmt = select(Employee).options(selectinload(Employee.tags)).order_by(
            Employee.active.desc(), Employee.name)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(Employee.name.ilike(like) | Employee.email.ilike(like)
                              | Employee.tags.any(Tag.uid.ilike(f"%{normalize_uid(q)}%")))
        employees = (await s.execute(stmt)).scalars().all()
        all_emps = (await s.execute(select(Employee).order_by(Employee.name))).scalars().all()
        unknown = (await s.execute(
            select(AuthEvent.tag_uid, func.max(AuthEvent.ts), func.count(),
                   func.max(AuthEvent.station_id))
            .where(AuthEvent.result == "Invalid", AuthEvent.tag_uid.not_in(select(Tag.uid)),
                   AuthEvent.ts > utcnow() - timedelta(days=30))
            .group_by(AuthEvent.tag_uid).order_by(func.max(AuthEvent.ts).desc()).limit(20))).all()
        sync = await s.get(SyncState, 1)
    return render(request, "employees.html", employees=employees, all_emps=all_emps,
                  unknown=unknown, q=q, sync=sync)


@web_app.post("/employees/add")
async def employee_add(request: Request, user=Depends(admin), name: str = Form(...),
                       email: str = Form(""), uid: str = Form("")):
    async with Session() as s:
        emp = Employee(name=name.strip(), email=email.strip().lower() or None)
        if uid.strip():
            emp.tags.append(Tag(uid=normalize_uid(uid)))
        s.add(emp)
        try:
            await s.commit()
            flash(request, _("{name} added", name=emp.name))
        except IntegrityError:
            flash(request, _("This tag is already assigned to another employee"), "err")
    core.schedule_push_all()
    return back("/employees")


@web_app.post("/employees/{emp_id}/toggle")
async def employee_toggle(request: Request, emp_id: int, user=Depends(admin)):
    async with Session() as s:
        if emp := await s.get(Employee, emp_id):
            emp.active = not emp.active
            await s.commit()
            if emp.source == "entra":
                flash(request, _("Note: employees from Entra are overwritten by the next sync"), "warn")
    core.schedule_push_all()
    return back("/employees")


@web_app.post("/employees/{emp_id}/edit")
async def employee_edit(request: Request, emp_id: int, user=Depends(admin), name: str = Form(...),
                        email: str = Form("")):
    async with Session() as s:
        emp = await s.get(Employee, emp_id)
        if emp is None:
            flash(request, _("Employee not found"), "err")
        elif emp.source == "entra":
            flash(request, _("Employees from Entra are maintained in Entra ID"), "err")
        elif not name.strip():
            flash(request, _("Name must not be empty"), "err")
        else:
            emp.name, emp.email = name.strip(), email.strip().lower() or None
            await s.commit()
            flash(request, _("{name} saved", name=emp.name))
            core.notify_all()
    return back("/employees")


@web_app.post("/employees/{emp_id}/delete")
async def employee_delete(request: Request, emp_id: int, user=Depends(admin)):
    async with Session() as s:
        if emp := await s.get(Employee, emp_id):
            await s.delete(emp)
            await s.commit()
    core.schedule_push_all()
    return back("/employees")


@web_app.post("/tags/add")
async def tag_add(request: Request, user=Depends(admin), uid: str = Form(...),
                  employee_id: str = Form(""), new_name: str = Form(""), label: str = Form("")):
    async with Session() as s:
        if employee_id:
            emp = await s.get(Employee, int(employee_id))
        elif new_name.strip():
            emp = Employee(name=new_name.strip())
            s.add(emp)
        else:
            flash(request, _("Please select an employee or enter a name"), "err")
            return back("/employees")
        if emp is None:
            flash(request, _("Employee not found"), "err")
            return back("/employees")
        tag = Tag(uid=normalize_uid(uid), label=label.strip() or None)
        if emp.id is None:
            emp.tags.append(tag)
        else:
            tag.employee_id = emp.id
            s.add(tag)
        try:
            await s.commit()
            flash(request, _("Tag {uid} → {name}", uid=normalize_uid(uid), name=emp.name))
        except IntegrityError:
            flash(request, _("This tag is already assigned"), "err")
    core.schedule_push_all()
    return back("/employees")


@web_app.post("/tags/{tag_id}/toggle")
async def tag_toggle(request: Request, tag_id: int, user=Depends(admin)):
    async with Session() as s:
        if tag := await s.get(Tag, tag_id):
            tag.active = not tag.active
            await s.commit()
    core.schedule_push_all()
    return back("/employees")


@web_app.post("/tags/{tag_id}/label")
async def tag_label(request: Request, tag_id: int, user=Depends(admin), label: str = Form("")):
    async with Session() as s:
        if tag := await s.get(Tag, tag_id):
            tag.label = label.strip() or None
            await s.commit()
    return back("/employees")


@web_app.post("/tags/{tag_id}/delete")
async def tag_delete(request: Request, tag_id: int, user=Depends(admin)):
    async with Session() as s:
        if tag := await s.get(Tag, tag_id):
            await s.delete(tag)
            await s.commit()
    core.schedule_push_all()
    return back("/employees")


@web_app.post("/sync")
async def sync_now(request: Request, user=Depends(admin)):
    if not config.ENTRA_SYNC_ENABLED:
        flash(request, _("Entra sync is not configured"), "err")
    else:
        result = await entra_sync.run_sync()
        flash(request, sync_summary(json.dumps(result)), "err" if "error" in result else "ok")
        core.schedule_push_all(delay=1)
    return back("/employees")


# --- Sessions & log -------------------------------------------------------------------------------

def _month_range(month: str) -> tuple[datetime, datetime, str]:
    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError:
        start = datetime.now(TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    end = (start + timedelta(days=32)).replace(day=1)

    def to_utc(d: datetime) -> datetime:
        return d.replace(tzinfo=TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    return to_utc(start), to_utc(end), start.strftime("%Y-%m")


async def _transactions(month: str, site_id: str):
    start, end, label = _month_range(month)
    async with Session() as s:
        stmt = (select(Transaction)
                .options(selectinload(Transaction.employee),
                         selectinload(Transaction.station).selectinload(Station.site))
                .where(Transaction.started_at >= start, Transaction.started_at < end)
                .order_by(Transaction.started_at.desc()))
        if site_id:
            stmt = stmt.join(Station).where(Station.site_id == int(site_id))
        txs = (await s.execute(stmt)).scalars().all()
        sites = (await s.execute(select(Site).order_by(Site.name))).scalars().all()
    return txs, sites, label


@web_app.get("/transactions", response_class=HTMLResponse)
async def transactions_page(request: Request, user=Depends(admin), month: str = "", site: str = ""):
    txs, sites, label = await _transactions(month, site)
    total = sum(t.energy_kwh or 0 for t in txs)
    per_emp: dict[str, float] = {}
    for t in txs:
        key = t.employee.name if t.employee else (t.tag_uid or _("no tag"))
        per_emp[key] = per_emp.get(key, 0) + (t.energy_kwh or 0)
    return render(request, "transactions.html", txs=txs, sites=sites, month=label, site=site,
                  total=total, per_emp=sorted(per_emp.items(), key=lambda x: -x[1]))


@web_app.get("/transactions.csv")
async def transactions_csv(user=Depends(admin), month: str = "", site: str = ""):
    txs, _sites, label = await _transactions(month, site)
    buf = io.StringIO()
    # German Excel expects ";" and decimal commas
    w = csv.writer(buf, delimiter=";" if i18n.current() == "de" else ",")
    w.writerow([_(h) for h in ("Start", "End", "Site", "Station", "Connector", "Employee", "Email",
                               "Tag", "kWh", "Meter start (Wh)", "Meter end (Wh)", "Stop reason")])
    for t in txs:
        w.writerow([local(t.started_at), local(t.stopped_at) if t.stopped_at else _("running"),
                    t.station.site.name if t.station and t.station.site else "",
                    (t.station.name or t.station_id) if t.station else t.station_id,
                    t.connector_id or "", t.employee.name if t.employee else "",
                    (t.employee.email or "") if t.employee else "", t.tag_uid or "",
                    i18n.number(t.energy_kwh, 3) if t.energy_kwh is not None else "",
                    t.meter_start_wh or "", t.meter_stop_wh or "", t.stop_reason or ""])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=sessions-{label}.csv"})


@web_app.get("/log", response_class=HTMLResponse)
async def log_page(request: Request, user=Depends(admin), result: str = ""):
    async with Session() as s:
        stmt = select(AuthEvent).options(selectinload(AuthEvent.employee)).order_by(
            AuthEvent.ts.desc()).limit(300)
        if result:
            stmt = stmt.where(AuthEvent.result == result)
        events = (await s.execute(stmt)).scalars().all()
        names = {st.id: st.name for st in (await s.execute(select(Station))).scalars().all()}
    return render(request, "log.html", events=events, result=result, names=names)


@web_app.get("/health")
async def health():
    return {"ok": True, "version": config.VERSION, "connected": len(core.connected)}
