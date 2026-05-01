from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord, TransferRequest
from app.services.transfer_decision_service import decide_transfer

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/transfers")
async def request_transfer(
    request: Request, body: TransferRequest, now: str | None = Query(None)
) -> dict[str, Any]:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else None
    decision = decide_transfer(tenant, now=now_dt)
    await state.event_log.append(
        EventRecord(
            call_sid=body.call_sid,
            kind="transfer_decided",
            payload={"decision": decision.model_dump(), "reason": body.reason},
        )
    )
    return decision.model_dump()
