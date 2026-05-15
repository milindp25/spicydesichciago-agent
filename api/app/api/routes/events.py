from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import CallEvent
from app.domain.models import EventRecord

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


class EventBody(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    caller_phone: str = ""
    from_number: str = ""


@router.post("/calls/{call_sid}/event", status_code=202)
async def append_call_event(request: Request, call_sid: str, body: EventBody) -> dict[str, Any]:
    state = get_state(request)
    # Legacy JSONL write (removed in Task 5.7).
    if state.event_log is not None:
        await state.event_log.append(
            EventRecord(call_sid=call_sid, kind=body.kind, payload=body.payload)
        )
    # Firestore write — auto-upserts parent /calls doc when missing.
    if state.call_store is not None:
        state.call_store.append_event(
            call_sid=call_sid,
            event=CallEvent(
                ts=datetime.now(timezone.utc), kind=body.kind, payload=body.payload
            ),
            caller_phone_for_upsert=body.caller_phone or "+0",
            from_number_for_upsert=body.from_number or "+0",
        )
    return {"ok": True}
