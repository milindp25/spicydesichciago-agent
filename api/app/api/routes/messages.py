from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord, MessageRequest

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/messages", status_code=202)
async def take_message(request: Request, body: MessageRequest) -> dict[str, Any]:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")

    sms_body = (
        f"Spicy Desi AI message — {body.caller_name or 'unknown'} "
        f"({body.callback_number}): {body.reason}"
    )
    sms_sent = await state.twilio.send_sms(to=tenant.owner_phone, body=sms_body)

    if tenant.sms_confirmation_to_caller and body.callback_number:
        confirmation = (
            f'Thanks for calling Spicy Desi. We got your message about "{body.reason}" '
            "and will call you back."
        )
        await state.twilio.send_sms(to=body.callback_number, body=confirmation)

    await state.event_log.append(
        EventRecord(
            call_sid=body.call_sid,
            kind="message_taken",
            payload={**body.model_dump(), "sms_sent": sms_sent},
        )
    )
    return {"ok": True, "sms_sent": sms_sent}
