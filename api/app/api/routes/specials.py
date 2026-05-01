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
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.catalog_service.get_specials()
    return {"items": [i.model_dump() for i in items]}
