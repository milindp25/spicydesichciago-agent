from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations/{location_id}/specials")
async def list_specials(
    request: Request, location_id: str, tenant: str = Query(..., min_length=1)
) -> dict[str, Any]:
    _ = location_id
    state = get_state(request)
    t = state.tenants.tenants.get(tenant)
    if t is None:
        raise HTTPException(404, "tenant not found")
    return {"items": [item.model_dump() for item in t.specials]}
