from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])

log = logging.getLogger(__name__)


@router.get("/specials")
async def list_specials(request: Request, tenant: str = Query(..., min_length=1)) -> dict[str, Any]:
    state = get_state(request)
    t = state.tenants.tenants.get(tenant)
    if t is None:
        raise HTTPException(404, "tenant not found")

    # Prefer live Square data (items tagged with SQUARE_SPECIALS_CATEGORY_ID).
    # Fall back to the static specials.json if Square returns nothing or errors.
    try:
        live = await state.catalog_service.get_specials()
    except Exception:
        log.exception("specials live fetch failed; falling back to static file")
        live = []

    items = live if live else t.specials
    return {"items": [item.model_dump() for item in items]}
