# SPDX-License-Identifier: MIT
# Copyright (c) 2026 KultiKom GmbH & Co. KG
"""Offline verification of KultiLic license keys – copy this single file into a product.

Only dependency: the `cryptography` package. The product embeds its PUBLIC key(s); the private
key never leaves the KultiLic server. Nobody can forge a key without it.

    from kultilic_verify import check

    PUBLIC_KEYS = {"1a2b3c4d": "base64url public key from the KultiLic product page"}

    result = check(key_text, PUBLIC_KEYS, product="chargegate", installation_id=my_install_id)
    if result.usable:
        allowed = result.limit("charging_points", default=2)

Key format: KL1.<base64url(JSON payload)>.<base64url(Ed25519 signature over "KL1.<payload>")>

Payload fields: v (format version), kid (key id), lid (license id), rev (revision), iss (issuer),
pid (product), typ (subscription|trial), cust (customer), cno (customer no.), iat (issued),
nbf (valid from), exp (valid until, inclusive), lim (limits dict), inst (installation id, optional).
Dates are ISO dates (YYYY-MM-DD) and interpreted in UTC.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

PREFIX = "KL1"

# status values
VALID = "valid"            # within the term
EXPIRING = "expiring"      # valid, ends within warn_days
GRACE = "grace"            # expired, but within grace_days – keep working, show a warning
EXPIRED = "expired"        # expired and grace is over
NOT_YET_VALID = "not_yet_valid"
INVALID = "invalid"        # malformed, unknown key id, bad signature, wrong product/installation


@dataclass
class LicenseCheck:
    status: str
    error: str | None = None
    claims: dict = field(default_factory=dict)
    days_left: int | None = None      # days until "valid until" (negative once expired)

    @property
    def usable(self) -> bool:
        """True while the product should honour the license (valid, expiring or in grace)."""
        return self.status in (VALID, EXPIRING, GRACE)

    def limit(self, name: str, default: int = 0) -> int:
        """A licensed limit, or `default` when the license is not usable / lacks the limit."""
        if not self.usable:
            return default
        try:
            return int(self.claims.get("lim", {}).get(name, default))
        except (TypeError, ValueError):
            return default

    @property
    def license_id(self) -> str | None:
        return self.claims.get("lid")

    @property
    def customer(self) -> str | None:
        return self.claims.get("cust")

    @property
    def valid_until(self) -> date | None:
        try:
            return date.fromisoformat(self.claims["exp"])
        except (KeyError, ValueError):
            return None


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def normalize(key: str) -> str:
    """Remove whitespace/line breaks that sneak in when keys are copied from e-mails."""
    return "".join((key or "").split())


def decode_unverified(key: str) -> dict:
    """Payload without checking anything – for display/debugging only."""
    parts = normalize(key).split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise ValueError("not a KultiLic key")
    return json.loads(_b64d(parts[1]))


def verify_signature(key: str, public_keys: dict[str, str]) -> dict:
    """Payload if the key was signed by one of `public_keys` ({kid: base64url raw key}), else ValueError."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    parts = normalize(key).split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise ValueError("not a KultiLic key")
    try:
        claims = json.loads(_b64d(parts[1]))
    except ValueError as exc:
        raise ValueError("payload unreadable") from exc
    if not isinstance(claims, dict) or claims.get("v") != 1:
        raise ValueError("unsupported key version")
    pub = public_keys.get(claims.get("kid", ""))
    if not pub:
        raise ValueError("unknown signing key")
    try:
        Ed25519PublicKey.from_public_bytes(_b64d(pub)).verify(_b64d(parts[2]), f"{parts[0]}.{parts[1]}".encode())
    except Exception as exc:  # InvalidSignature, malformed base64 …
        raise ValueError("signature invalid") from exc
    return claims


def check(key: str, public_keys: dict[str, str], *, product: str, installation_id: str | None = None,
          today: date | None = None, warn_days: int = 30, grace_days: int = 14) -> LicenseCheck:
    """Full check: signature, product, installation binding and term."""
    try:
        claims = verify_signature(key, public_keys)
    except ValueError as exc:
        return LicenseCheck(INVALID, str(exc))
    if claims.get("pid") != product:
        return LicenseCheck(INVALID, f"license is for product {claims.get('pid')!r}", claims)
    if claims.get("inst") and claims.get("inst") != installation_id:
        return LicenseCheck(INVALID, "license is bound to another installation", claims)
    try:
        nbf, exp = date.fromisoformat(claims["nbf"]), date.fromisoformat(claims["exp"])
    except (KeyError, ValueError):
        return LicenseCheck(INVALID, "term missing", claims)
    today = today or datetime.now(timezone.utc).date()
    left = (exp - today).days
    if today < nbf:
        return LicenseCheck(NOT_YET_VALID, None, claims, left)
    if today <= exp:
        return LicenseCheck(EXPIRING if left < warn_days else VALID, None, claims, left)
    if today <= exp + timedelta(days=grace_days):
        return LicenseCheck(GRACE, None, claims, left)
    return LicenseCheck(EXPIRED, None, claims, left)


if __name__ == "__main__":   # python kultilic_verify.py <key> <kid>=<public key> --product chargegate
    import argparse

    ap = argparse.ArgumentParser(description="Check a KultiLic license key offline")
    ap.add_argument("key")
    ap.add_argument("public_key", nargs="+", help="kid=base64url (from the KultiLic product page)")
    ap.add_argument("--product", required=True)
    ap.add_argument("--installation-id")
    a = ap.parse_args()
    r = check(a.key, dict(p.split("=", 1) for p in a.public_key), product=a.product,
              installation_id=a.installation_id)
    print(json.dumps({"status": r.status, "error": r.error, "days_left": r.days_left, "claims": r.claims},
                     indent=2, ensure_ascii=False))
