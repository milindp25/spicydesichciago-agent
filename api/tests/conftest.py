from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app_factory import build_app
from app.api.dependencies import AppState
from app.domain.models import OwnerAvailable, Tenant
from app.infrastructure.cache import TtlCache
from app.infrastructure.event_log import JsonlEventLog
from app.infrastructure.tenant_registry import TenantRegistry
from app.services.catalog_service import CatalogService
from app.services.locations_service import LocationsService
from tests.helpers.square_mock import FakeCatalogApi, FakeLocationsApi

SHARED_SECRET = "s" * 32


def _build_tenant() -> Tenant:
    return Tenant(
        slug="spicy-desi",
        name="Spicy Desi",
        twilio_number="+15555550100",
        owner_phone="+15555550199",
        owner_available=OwnerAvailable(tz="America/Chicago", weekly={"mon": ("11:00", "21:30")}),
        square_merchant_id="M1",
        languages=["en"],
        sms_confirmation_to_caller=True,
        location_overrides={},
        faq="",
        location_notes="",
    )


@pytest.fixture
def secret() -> str:
    return SHARED_SECRET


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-Tools-Auth": SHARED_SECRET}


@pytest.fixture
def client_factory(
    tmp_path: Path,
) -> Callable[..., tuple[TestClient, AppState]]:
    def _build(
        locations: list[dict[str, Any]] | None = None,
        catalog_items: list[dict[str, Any]] | None = None,
    ) -> tuple[TestClient, AppState]:
        tenant = _build_tenant()
        registry = TenantRegistry(
            tenants={tenant.slug: tenant},
            by_twilio_number={tenant.twilio_number: tenant.slug},
        )
        loc_svc = LocationsService(api=FakeLocationsApi(locations or []), cache=TtlCache(60))
        cat_svc = CatalogService(
            api=FakeCatalogApi(catalog_items or []),
            cache=TtlCache(60),
            specials_category_id="SPECIALS",
        )
        log = JsonlEventLog(str(tmp_path / "events.jsonl"))
        state = AppState(
            tools_shared_secret=SHARED_SECRET,
            tenants=registry,
            locations_service=loc_svc,
            catalog_service=cat_svc,
            event_log=log,
            square_webhook_signature_key="key",
            square_webhook_url="https://example.com/api/webhooks/square",
        )
        return TestClient(build_app(state)), state

    return _build


@pytest.fixture
def client(client_factory: Callable[..., tuple[TestClient, AppState]]) -> Iterator[TestClient]:
    c, _ = client_factory()
    with c:
        yield c
