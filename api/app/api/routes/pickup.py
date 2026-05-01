from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import SetPickupRequest

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/pickup/today")
async def get_pickup_today(
    request: Request, tenant: str = Query(..., min_length=1)
) -> dict[str, Any]:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    pickup = await state.pickup_service.get_today(tenant)
    if pickup is None:
        return {"pickup": None}
    return {"pickup": pickup.model_dump()}


@router.post("/admin/pickup")
async def set_pickup(request: Request, body: SetPickupRequest) -> dict[str, Any]:
    state = get_state(request)
    if body.tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    try:
        record = await state.pickup_service.set_today(body.tenant, body.location_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {
        "ok": True,
        "tenant": body.tenant,
        "location_id": record.location_id,
        "set_at": record.set_at,
        "set_for_date": record.set_for_date,
    }
