from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


class EventBody(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/calls/{call_sid}/event", status_code=202)
async def append_call_event(request: Request, call_sid: str, body: EventBody) -> dict[str, Any]:
    state = get_state(request)
    await state.event_log.append(
        EventRecord(call_sid=call_sid, kind=body.kind, payload=body.payload)
    )
    return {"ok": True}
