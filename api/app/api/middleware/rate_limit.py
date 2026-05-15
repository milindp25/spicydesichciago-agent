"""slowapi rate limiter for the API.

Strategy: IP-based, generous default (120 req/min). Set RATE_LIMIT_DEFAULT
env var to override (e.g., for tests).

A future iteration may add per-uid limits for authenticated dashboard
traffic, but FastAPI deps run after middleware so the verified UID
isn't available at limit-evaluation time without extra wiring.
"""
from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address


def _key_func(request) -> str:
    return f"ip:{get_remote_address(request)}"


def build_limiter() -> Limiter:
    default = os.environ.get("RATE_LIMIT_DEFAULT", "120/minute")
    return Limiter(key_func=_key_func, default_limits=[default])
