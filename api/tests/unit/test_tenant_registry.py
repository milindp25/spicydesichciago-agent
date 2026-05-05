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


def _write_min_tenant(tmp_path: Path, owner_available: dict) -> None:
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
                "owner_available": owner_available,
                "languages": ["en"],
                "sms_confirmation_to_caller": True,
                "location_overrides": {},
            }
        )
    )
    (sd / "faq.md").write_text("")
    (sd / "location-notes.md").write_text("")


def test_default_window_applies_to_every_day(tmp_path: Path) -> None:
    _write_min_tenant(
        tmp_path,
        {"tz": "America/Chicago", "default_window": ["08:00", "22:00"]},
    )
    reg = load_tenants(str(tmp_path))
    weekly = reg.tenants["spicy-desi"].owner_available.weekly
    assert len(weekly) == 7
    assert weekly["mon"] == ("08:00", "22:00")
    assert weekly["sun"] == ("08:00", "22:00")


def test_weekly_overrides_default_window(tmp_path: Path) -> None:
    _write_min_tenant(
        tmp_path,
        {
            "tz": "America/Chicago",
            "default_window": ["08:00", "22:00"],
            "weekly": {"fri": ["08:00", "23:30"], "sun": None},
        },
    )
    reg = load_tenants(str(tmp_path))
    weekly = reg.tenants["spicy-desi"].owner_available.weekly
    assert weekly["mon"] == ("08:00", "22:00")
    assert weekly["fri"] == ("08:00", "23:30")
    assert "sun" not in weekly  # null removes the day


def test_weekly_only_still_works(tmp_path: Path) -> None:
    _write_min_tenant(
        tmp_path,
        {"tz": "America/Chicago", "weekly": {"mon": ["11:00", "21:30"]}},
    )
    reg = load_tenants(str(tmp_path))
    weekly = reg.tenants["spicy-desi"].owner_available.weekly
    assert weekly == {"mon": ("11:00", "21:30")}


def test_env_var_substitution_in_tenant_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OWNER_PHONE", "+13125550000")
    monkeypatch.setenv("ORDER_URL", "https://example.com/order")
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
                "owner_phone": "${OWNER_PHONE}",
                "owner_available": {
                    "tz": "America/Chicago",
                    "weekly": {"mon": ["11:00", "21:30"]},
                },
                "languages": ["en"],
                "sms_confirmation_to_caller": True,
                "location_overrides": {},
                "order_url": "${ORDER_URL}",
            }
        )
    )
    (sd / "faq.md").write_text("")
    (sd / "location-notes.md").write_text("")

    reg = load_tenants(str(tmp_path))
    t = reg.tenants["spicy-desi"]
    assert t.owner_phone == "+13125550000"
    assert t.order_url == "https://example.com/order"
