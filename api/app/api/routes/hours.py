from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations/{location_id}/hours/today")
async def hours_today(
    request: Request,
    location_id: str,
    tenant: str = Query(..., min_length=1),
    now: str | None = Query(None),
) -> dict[str, Any]:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else None
    try:
        result = await state.locations_service.get_hours_today(location_id, now=now_dt)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return result.model_dump()
