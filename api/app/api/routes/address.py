from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations/{location_id}/address")
async def get_address(
    request: Request, location_id: str, tenant: str = Query(..., min_length=1)
) -> dict[str, Any]:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    try:
        result = await state.locations_service.get_address(location_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return result.model_dump()
