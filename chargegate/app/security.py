# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Hardening helpers: security headers and request checks for the web UI, brute-force brakes for
the admin login and for tag/PIN checks of stations, safe CSV cells, station ID rules."""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("chargegate.security")

MAX_BODY = 1_000_000                      # bytes – forms and the site plan are far smaller
STATION_ID = re.compile(r"[A-Za-z0-9._:@~-]{1,64}")   # no characters that break URLs
MAX_PENDING_STATIONS = 50

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; font-src 'self' data:; object-src 'none'; "
       "base-uri 'self'; frame-ancestors 'self'; form-action 'self'")
HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"x-frame-options", b"SAMEORIGIN"),          # Home Assistant ingress frames it from the same origin
    (b"content-security-policy", CSP.encode()),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityMiddleware:
    """Security headers on every response; rejects oversized bodies and cross-site form posts.

    Cross-site requests are recognised by the browser's Sec-Fetch-Site header (sent by all current
    browsers). Together with the SameSite session cookie this blocks CSRF – also via Home Assistant
    ingress, where the user is authenticated by Home Assistant instead of our cookie.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope.get("headers", [])}
        if scope.get("method") in UNSAFE_METHODS:
            if headers.get("sec-fetch-site") == "cross-site":
                log.warning("Blocked cross-site %s %s from %s", scope["method"], scope.get("path"),
                            (scope.get("client") or ("?",))[0])
                return await _plain(send, 403, b"Cross-site request blocked")
            try:
                if int(headers.get("content-length") or 0) > MAX_BODY:
                    return await _plain(send, 413, b"Request too large")
            except ValueError:
                return await _plain(send, 400, b"Bad request")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _v in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [h for h in HEADERS if h[0] not in have]
            await send(message)

        return await self.app(scope, receive, send_with_headers)


async def _plain(send, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), *HEADERS]})
    await send({"type": "http.response.body", "body": body})


class Throttle:
    """Counts failures per key; after `limit` failures within `window` s the key is locked.

    Each further lock doubles (up to `max_lock` s). Kept in memory – a restart resets it.
    """

    def __init__(self, limit: int, window: float, lock: float, max_lock: float):
        self.limit, self.window, self.lock, self.max_lock = limit, window, lock, max_lock
        self._fails: dict[str, list[float]] = {}
        self._locked: dict[str, tuple[float, float]] = {}      # key -> (until, last lock length)

    def locked_for(self, key: str, now: float | None = None) -> int:
        now = now or time.monotonic()
        until = self._locked.get(key, (0, 0))[0]
        return max(0, int(until - now + 0.999))

    def fail(self, key: str, now: float | None = None) -> bool:
        """Record a failure. Returns True if the key just got locked."""
        now = now or time.monotonic()
        fails = [t for t in self._fails.get(key, []) if now - t < self.window] + [now]
        self._fails[key] = fails
        if len(fails) >= self.limit:
            last = self._locked.get(key, (0, 0))[1]
            length = min(self.max_lock, last * 2 if last else self.lock)
            self._locked[key] = (now + length, length)
            self._fails[key] = []
            return True
        if len(self._fails) > 10_000:                        # don't grow without bound
            self._fails = {k: v for k, v in self._fails.items() if v and now - v[-1] < self.window}
        return False

    def success(self, key: str) -> None:
        self._fails.pop(key, None)
        self._locked.pop(key, None)


# Admin login: 5 wrong passwords per IP within 10 min -> locked 1 min, then 2, 4 … up to 30 min
login_throttle = Throttle(limit=5, window=600, lock=60, max_lock=1800)
# Station passwords (OCPP basic auth): 10 failures per IP within 10 min -> 5 min, doubling up to 1 h
station_throttle = Throttle(limit=10, window=600, lock=300, max_lock=3600)
# Tag/PIN checks: 20 unknown tags per station within 10 min -> that station's checks are refused
# for 5 min, then 10 … up to 60 min. Real stations rarely see more than a few unknown cards.
auth_throttle = Throttle(limit=20, window=600, lock=300, max_lock=3600)


def csv_cell(value):
    """Neutralise spreadsheet formulas (=, +, -, @ …) in text exported to CSV."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def valid_station_id(station_id: str) -> bool:
    return bool(STATION_ID.fullmatch(station_id or ""))
