from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import CallEvent, EventKind
from app.domain.message import Message
from app.domain.models import MessageRequest

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/messages", status_code=202)
async def take_message(request: Request, body: MessageRequest) -> dict[str, Any]:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")

    try:
        received = datetime.now().strftime("%-I:%M %p")
    except ValueError:
        received = datetime.now().strftime("%I:%M %p").lstrip("0")
    caller_label = body.caller_name or "unknown caller"
    sms_body = (
        f"Spicy Desi voice agent — message at {received}\n"
        f"{caller_label} ({body.callback_number}): {body.reason}\n"
        f"Call back: tel:{body.callback_number}"
    )
    sms_sent = await state.twilio.send_sms(to=tenant.owner_phone, body=sms_body)

    if tenant.sms_confirmation_to_caller and body.callback_number:
        reason_snippet = (body.reason or "")[:80]
        callback_num = (tenant.twilio_number or "").strip()
        # Skip placeholders like "+15555550100"-ish tokens that look unset.
        is_placeholder = not callback_num
        lines = [
            f'Thanks for calling Spicy Desi. Got your message about "{reason_snippet}"'
            + (f" — the owner will call you back from {callback_num}." if not is_placeholder else " — the owner will call you back.")
        ]
        if not is_placeholder:
            lines.append(
                f"Need to reach us sooner? Reply to this text or call {callback_num}."
            )
        confirmation = "\n".join(lines)
        await state.twilio.send_sms(to=body.callback_number, body=confirmation)

    now = datetime.now(timezone.utc)

    # 1) Primary record in /messages
    msg = Message(
        call_sid=body.call_sid,
        caller_phone=body.callback_number,
        caller_name=body.caller_name,
        reason=body.reason,
        taken_at=now,
    )
    message_id = state.message_store.create(msg)

    # 2) Mirror as a call event under /calls/{sid}/events
    state.call_store.append_event(
        call_sid=body.call_sid,
        event=CallEvent(
            ts=now,
            kind=EventKind.MESSAGE_TAKEN.value,
            payload={**body.model_dump(), "sms_sent": sms_sent, "message_id": message_id},
        ),
        caller_phone_for_upsert=body.callback_number,
        from_number_for_upsert=tenant.twilio_number,
    )

    return {"ok": True, "sms_sent": sms_sent, "message_id": message_id}
