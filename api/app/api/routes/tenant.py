from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth
from app.services.transfer_decision_service import decide_transfer

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/tenant")
async def get_tenant(request: Request, tenant: str = Query(...)) -> dict[str, Any]:
    """Lightweight tenant snapshot used by the agent at call start.

    Returns the greeting line + whether the owner is currently reachable.
    The agent uses these to skip transfer attempts when it's after-hours
    (caller hears "I'll take a message" instead of an empty ringback).
    """
    state = get_state(request)
    tenant_obj = state.tenants.tenants.get(tenant)
    if tenant_obj is None:
        raise HTTPException(404, "tenant not found")
    decision = decide_transfer(tenant_obj)
    return {
        "slug": tenant_obj.slug,
        "name": tenant_obj.name,
        "greeting": tenant_obj.greeting,
        "owner_available": decision.action == "transfer",
        "languages": tenant_obj.languages,
    }
