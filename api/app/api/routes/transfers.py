from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import TransferRequest
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
    decision = decide_transfer(
        tenant, now=now_dt, owner_override_store=state.owner_override_store
    )

    redirect_ok = False
    if decision.action == "transfer" and state.agent_public_url:
        twiml_url = f"{state.agent_public_url}/twilio/dial-owner?to={tenant.owner_phone}"
        redirect_ok = await state.twilio.redirect_call(call_sid=body.call_sid, twiml_url=twiml_url)

    return {**decision.model_dump(), "redirect_ok": redirect_ok}
