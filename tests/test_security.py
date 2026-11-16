# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Hardening: throttles, CSV cells, station IDs, tag guessing, name lookups, web headers and checks."""
from __future__ import annotations

import asyncio

import core
import security
import vehicles
from db import Employee, Session, Tag, init_db
from starlette.testclient import TestClient


def test_throttle_locks_and_doubles():
    th = security.Throttle(limit=3, window=60, lock=10, max_lock=25)
    assert not th.fail("a", 0) and not th.fail("a", 1)
    assert th.fail("a", 2) and th.locked_for("a", 3) == 9
    assert th.locked_for("b", 3) == 0                       # per key
    for t in (20, 21, 22):
        th.fail("a", t)
    assert th.locked_for("a", 22) == 20                     # second lock: doubled
    for t in (50, 51, 52):
        th.fail("a", t)
    assert th.locked_for("a", 52) == 25                     # capped
    th.success("a")
    assert th.locked_for("a", 53) == 0


def test_csv_and_station_ids():
    assert security.csv_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert security.csv_cell("@SUM(A1)") == "'@SUM(A1)" and security.csv_cell("Anna") == "Anna"
    assert security.csv_cell(12.5) == 12.5
    assert security.valid_station_id("KULTIWB-01") and security.valid_station_id("ACE0815.2:x")
    assert not security.valid_station_id("a b") and not security.valid_station_id("<script>")
    assert not security.valid_station_id("x" * 65) and not security.valid_station_id("a#b")


def test_tag_guessing_is_braked_and_names_need_an_accepted_tag():
    async def run():
        await init_db()
        async with Session() as s:
            e = Employee(name="Erika Geheim")
            e.tags.append(Tag(uid="4711"))
            s.add(e)
            await s.commit()
        # a station may only ask for the name of a tag it had accepted just before
        assert await core.employee_name("4711", "GUESS-1") is None
        assert (await core.authorize("GUESS-1", "4711"))[0] == "Accepted"
        assert await core.employee_name("4711", "GUESS-1") == "Erika Geheim"
        assert await core.employee_name("4711", "OTHER") is None
        # guessing PINs: after 20 unknown ones the station's checks are refused
        for pin in range(1000, 1020):
            assert (await core.authorize("GUESS-2", str(pin)))[0] == "Invalid"
        assert (await core.authorize("GUESS-2", "4711"))[0] == "Invalid"
        assert (await core.authorize("GUESS-3", "4711"))[0] == "Accepted"   # other stations unaffected
        security.auth_throttle.success("GUESS-2")
    asyncio.run(run())


def test_mqtt_car_ids_are_checked():
    assert vehicles.parse_topic("teslamate", "teslamate/cars/1/battery_level") == ("1", "battery_level")
    assert vehicles.parse_topic("teslamate", "teslamate/cars/<x>/battery_level") is None
    assert vehicles.parse_topic("teslamate", "teslamate/cars/" + "9" * 40 + "/battery_level") is None


def test_web_headers_csrf_size_login_and_escaping():
    import web
    asyncio.run(init_db())
    with TestClient(web.web_app) as c:
        r = c.get("/login")
        assert r.headers["x-frame-options"] == "SAMEORIGIN"
        assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
        assert r.headers["x-content-type-options"] == "nosniff"
        # cross-site form post (CSRF) and oversized bodies are rejected
        assert c.post("/login", data={"password": "x"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.post("/plan/none", content=b"x" * (security.MAX_BODY + 1),
                      headers={"Content-Type": "application/json"}).status_code == 413
        # login: correct password works, then 5 wrong ones lock the address
        r = c.post("/login", data={"password": "test-password-123"}, headers={"Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 200 and "/login" not in str(r.url)
        # car names from MQTT can't break out of the confirm() text on the Vehicles page
        async def car():
            import licensing
            await licensing.set_setting("vehicle_source", "teslamate")
            v = await vehicles.handle("teslamate", "66", "display_name", "x');alert(1)//\"")
            return v
        asyncio.run(car())
        page = c.get("/vehicles").text
        snippet = page[page.index("confirm("):page.index("confirm(") + 160]
        print(snippet)
        assert "alert(1)" in snippet and "x&#39;);alert" not in snippet.replace("\\u0027", "")
        assert "confirm('" not in page and 'confirm("' not in page
        c.get("/logout")
        for _ in range(5):
            c.post("/login", data={"password": "wrong"})
        r = c.post("/login", data={"password": "test-password-123"})
        assert "/login" in str(r.url)                      # locked, even with the right password
        security.login_throttle.success("testclient")
