from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Any

from fastapi import Header, HTTPException, Request, status

from app.api.middleware.firebase_auth import AuthError, FirebaseAuthVerifier
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_caller_store import FirestoreCallerStore
from app.infrastructure.firestore_message_store import FirestoreMessageStore
from app.infrastructure.firestore_owner_override_store import FirestoreOwnerOverrideStore
from app.infrastructure.tenant_registry import TenantRegistry
from app.infrastructure.twilio_client import TwilioOps
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
    square_webhook_signature_key: str
    square_webhook_url: str
    twilio: TwilioOps
    call_store: FirestoreCallStore
    caller_store: FirestoreCallerStore
    message_store: FirestoreMessageStore
    owner_override_store: FirestoreOwnerOverrideStore
    admin_verifier: FirebaseAuthVerifier
    agent_public_url: str = ""
    cors_origins: list[str] = field(default_factory=list)


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


async def require_admin_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """FastAPI dependency for /api/admin/* routes. Verifies the Bearer
    token and returns the decoded Firebase claims (uid, email, etc.).

    Raises:
        HTTPException(401) on missing/invalid token.
        HTTPException(403) on email not in allowlist.
    """
    state = get_state(request)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing Authorization Bearer token")
    token = authorization[len("Bearer "):].strip()
    try:
        return state.admin_verifier.verify(token)
    except AuthError as e:
        msg = str(e).lower()
        if "not in" in msg or "allowlist" in msg or "not authorized" in msg or "not verified" in msg:
            raise HTTPException(status_code=403, detail=str(e)) from e
        raise HTTPException(status_code=401, detail=str(e)) from e
