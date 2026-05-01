from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, status

from app.infrastructure.event_log import JsonlEventLog
from app.infrastructure.tenant_registry import TenantRegistry
from app.services.catalog_service import CatalogService
from app.services.locations_service import LocationsService


@dataclass
class AppState:
    tools_shared_secret: str
    tenants: TenantRegistry
    locations_service: LocationsService
    catalog_service: CatalogService
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
    if not x_tools_auth or not _consteq(x_tools_auth, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _consteq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode(), strict=False):
        result |= x ^ y
    return result == 0
