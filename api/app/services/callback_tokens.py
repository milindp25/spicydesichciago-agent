"""Stdlib-only signed token codec for owner-callback links.

Format: `<payload-b64>.<sig-b64>` where payload-b64 is url-safe base64 of a
JSON-encoded dict (which must contain an integer `exp` Unix timestamp) and
sig-b64 is url-safe base64 of HMAC-SHA256(payload-b64, secret).

Compact, JWT-ish but DIY — no third-party libs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload_b64: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(mac)


def encode(payload: dict[str, Any], *, secret: str, ttl_seconds: int) -> str:
    """Encode `payload` plus an `exp` claim into a signed compact token."""
    if not secret:
        raise ValueError("secret required")
    body = dict(payload)
    body["exp"] = int(time.time()) + int(ttl_seconds)
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64encode(raw)
    sig_b64 = _sign(payload_b64, secret)
    return f"{payload_b64}.{sig_b64}"


def decode(token: str, *, secret: str, now_unix: int | None = None) -> dict[str, Any]:
    """Verify signature + expiry. Returns the decoded payload (incl. exp).

    Raises ValueError on any failure (malformed, bad sig, expired).
    """
    if not secret:
        raise ValueError("secret required")
    if not token or token.count(".") != 1:
        raise ValueError("malformed token")
    payload_b64, sig_b64 = token.split(".", 1)
    expected_sig = _sign(payload_b64, secret)
    if not hmac.compare_digest(expected_sig, sig_b64):
        raise ValueError("bad signature")
    try:
        raw = _b64decode(payload_b64)
        body = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ValueError("malformed payload") from e
    if not isinstance(body, dict) or "exp" not in body:
        raise ValueError("missing exp")
    now = int(now_unix if now_unix is not None else time.time())
    if int(body["exp"]) < now:
        raise ValueError("expired")
    return body
