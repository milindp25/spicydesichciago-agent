import json
from pathlib import Path

import pytest

from app.infrastructure.tenant_registry import (
    load_tenants,
    lookup_tenant_by_twilio_number,
)


@pytest.fixture
def configs_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.json").write_text(
        json.dumps({"tenants_by_twilio_number": {"+15555550100": "spicy-desi"}})
    )
    sd = tmp_path / "spicy-desi"
    sd.mkdir()
    (sd / "tenant.json").write_text(
        json.dumps(
            {
                "slug": "spicy-desi",
                "name": "Spicy Desi",
                "twilio_number": "+15555550100",
                "owner_phone": "+15555550199",
                "owner_available": {
                    "tz": "America/Chicago",
                    "weekly": {"mon": ["11:00", "21:30"]},
                },
                "square_merchant_id": "M1",
                "languages": ["en"],
                "sms_confirmation_to_caller": True,
                "location_overrides": {},
            }
        )
    )
    (sd / "faq.md").write_text("# FAQ")
    (sd / "location-notes.md").write_text("# Loc")
    return tmp_path


def test_load_tenants(configs_dir: Path) -> None:
    reg = load_tenants(str(configs_dir))
    assert "spicy-desi" in reg.tenants
    assert reg.tenants["spicy-desi"].name == "Spicy Desi"
    assert reg.tenants["spicy-desi"].faq.startswith("# FAQ")


def test_lookup_by_twilio_number(configs_dir: Path) -> None:
    reg = load_tenants(str(configs_dir))
    t = lookup_tenant_by_twilio_number(reg, "+15555550100")
    assert t is not None and t.slug == "spicy-desi"


def test_lookup_unknown_returns_none(configs_dir: Path) -> None:
    reg = load_tenants(str(configs_dir))
    assert lookup_tenant_by_twilio_number(reg, "+19999999999") is None
