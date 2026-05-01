from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations")
async def list_locations(
    request: Request, tenant: str = Query(..., min_length=1)
) -> dict[str, Any]:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.locations_service.list_locations()
    return {"locations": [item.model_dump() for item in items]}
