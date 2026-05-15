"""Dashboard owner-override endpoints: get/set/clear."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.dependencies import get_state, require_admin_user
from app.domain.owner_override import OwnerOverride

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])


class SetOverrideBody(BaseModel):
    until_iso: str
    reason: str


def _serialize(o: OwnerOverride | None) -> dict[str, Any]:
    if o is None:
        return {
            "active": False,
            "untilIso": None,
            "reason": None,
            "setBy": None,
            "setAt": None,
        }
    return {
        "active": o.active,
        "untilIso": o.until_iso,
        "reason": o.reason,
        "setBy": o.set_by,
        "setAt": o.set_at.isoformat() if o.set_at else None,
    }


@router.get("/owner-override")
async def get_override(request: Request) -> dict[str, Any]:
    state = get_state(request)
    return _serialize(state.owner_override_store.get_current())


@router.post("/owner-override")
async def set_override(
    request: Request,
    body: SetOverrideBody,
    user: dict = Depends(require_admin_user),
) -> dict[str, Any]:
    # Validate until_iso parses and is in the future
    try:
        until_dt = datetime.fromisoformat(body.until_iso.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid until_iso: {e}") from e
    if until_dt <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="until_iso must be in the future")

    state = get_state(request)
    override = OwnerOverride(
        active=True,
        until_iso=body.until_iso,
        reason=body.reason,
        set_by=user["uid"],
        set_at=datetime.now(timezone.utc),
    )
    state.owner_override_store.set(override)
    return _serialize(state.owner_override_store.get_current())


@router.delete("/owner-override")
async def clear_override(
    request: Request,
    user: dict = Depends(require_admin_user),
) -> dict[str, Any]:
    state = get_state(request)
    state.owner_override_store.clear(cleared_by=user["uid"])
    return _serialize(state.owner_override_store.get_current())
