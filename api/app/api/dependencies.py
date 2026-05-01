from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, status

from app.infrastructure.event_log import JsonlEventLog
from app.infrastructure.tenant_registry import TenantRegistry
from app.services.catalog_service import CatalogService
from app.services.locations_service import LocationsService
from app.services.pickup_service import PickupService


@dataclass
class AppState:
    tools_shared_secret: str
    tenants: TenantRegistry
    locations_service: LocationsService
    catalog_service: CatalogService
    pickup_service: PickupService
    event_log: JsonlEventLog
    square_webhook_signature_key: str
    square_webhook_url: str


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.deps
    return state


def require_tools_auth(
    request: Request,
    x_tools_auth: str | None = Header(default=None),
) -> None:
    expected = get_state(request).tools_shared_secret
    provided = x_tools_auth or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
