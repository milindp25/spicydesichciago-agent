from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord, MessageRequest

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/messages", status_code=202)
async def take_message(request: Request, body: MessageRequest) -> dict[str, Any]:
    state = get_state(request)
    await state.event_log.append(
        EventRecord(call_sid=body.call_sid, kind="message_taken", payload=body.model_dump())
    )
    return {"ok": True, "sms_sent": False}
