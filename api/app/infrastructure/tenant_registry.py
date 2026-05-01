from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import MenuItem, OwnerAvailable, Tenant


@dataclass(frozen=True)
class TenantRegistry:
    tenants: dict[str, Tenant]
    by_twilio_number: dict[str, str]


def load_tenants(configs_dir: str) -> TenantRegistry:
    base = Path(configs_dir)
    index = json.loads((base / "index.json").read_text())
    tenants: dict[str, Tenant] = {}
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        tj = json.loads((entry / "tenant.json").read_text())
        weekly_raw = tj["owner_available"]["weekly"]
        weekly: dict[str, tuple[str, str]] = {
            day: (window[0], window[1]) for day, window in weekly_raw.items()
        }
        specials_file = entry / "specials.json"
        specials_raw = json.loads(specials_file.read_text()) if specials_file.exists() else []
        specials = [MenuItem.model_validate(item) for item in specials_raw]

        tenants[tj["slug"]] = Tenant(
            slug=tj["slug"],
            name=tj["name"],
            twilio_number=tj["twilio_number"],
            owner_phone=tj["owner_phone"],
            owner_available=OwnerAvailable(tz=tj["owner_available"]["tz"], weekly=weekly),
            square_merchant_id=tj["square_merchant_id"],
            languages=tj["languages"],
            sms_confirmation_to_caller=tj["sms_confirmation_to_caller"],
            location_overrides=tj.get("location_overrides", {}),
            faq=(entry / "faq.md").read_text(),
            location_notes=(entry / "location-notes.md").read_text(),
            specials=specials,
        )
    return TenantRegistry(tenants=tenants, by_twilio_number=index["tenants_by_twilio_number"])


def lookup_tenant_by_twilio_number(reg: TenantRegistry, number: str) -> Tenant | None:
    slug = reg.by_twilio_number.get(number)
    return reg.tenants.get(slug) if slug else None
