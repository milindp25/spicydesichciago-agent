from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.models import MenuItem, OwnerAvailable, Tenant

_ENV_REF = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """Substitute ${ENV_VAR} references inside string values, recursively.

    Lets tenant config files reference env vars for anything per-deploy
    or sensitive (phone numbers, URLs, merchant IDs) without committing them.
    Missing env vars resolve to an empty string.
    """
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass(frozen=True)
class TenantRegistry:
    tenants: dict[str, Tenant]
    by_twilio_number: dict[str, str]


_ALL_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _expand_weekly(owner_available: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Build the per-day window map from `default_window` + optional `weekly` overrides.

    Tenant config can specify either:
      - `default_window: ["08:00", "22:00"]` — applied to every day, or
      - `weekly: {"mon": ["11:00", "21:30"], ...}` — explicit per-day, or
      - both — `default_window` fills, `weekly` overrides specific days.
    Setting a day to `null` in `weekly` removes that day from the window
    (owner unavailable that day).
    """
    weekly: dict[str, tuple[str, str]] = {}
    default = owner_available.get("default_window")
    if default:
        for day in _ALL_DAYS:
            weekly[day] = (default[0], default[1])

    overrides = owner_available.get("weekly") or {}
    for day, window in overrides.items():
        if window is None:
            weekly.pop(day, None)
        else:
            weekly[day] = (window[0], window[1])

    if not weekly:
        raise ValueError("owner_available must define default_window or weekly")
    return weekly


def load_tenants(configs_dir: str) -> TenantRegistry:
    base = Path(configs_dir)
    index = json.loads((base / "index.json").read_text())
    tenants: dict[str, Tenant] = {}
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        tj = _expand_env(json.loads((entry / "tenant.json").read_text()))
        weekly = _expand_weekly(tj["owner_available"])
        specials_file = entry / "specials.json"
        specials_raw = json.loads(specials_file.read_text()) if specials_file.exists() else []
        specials = [MenuItem.model_validate(item) for item in specials_raw]

        tenants[tj["slug"]] = Tenant(
            slug=tj["slug"],
            name=tj["name"],
            twilio_number=tj["twilio_number"],
            owner_phone=tj["owner_phone"],
            owner_available=OwnerAvailable(tz=tj["owner_available"]["tz"], weekly=weekly),
            languages=tj["languages"],
            sms_confirmation_to_caller=tj["sms_confirmation_to_caller"],
            location_overrides=tj.get("location_overrides", {}),
            faq=(entry / "faq.md").read_text(),
            location_notes=(entry / "location-notes.md").read_text(),
            specials=specials,
            order_url=tj.get("order_url", ""),
            greeting=tj.get("greeting", ""),
            owner_phone_is_temporary=tj.get("owner_phone_is_temporary", False),
        )
    return TenantRegistry(tenants=tenants, by_twilio_number=index["tenants_by_twilio_number"])


def lookup_tenant_by_twilio_number(reg: TenantRegistry, number: str) -> Tenant | None:
    slug = reg.by_twilio_number.get(number)
    return reg.tenants.get(slug) if slug else None
