"""POST /api/calls/{sid}/start, /end, /summary — call lifecycle endpoints
used by the agent. Writes to FirestoreCallStore.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import Call, Outcome

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


class StartBody(BaseModel):
    started_at: datetime
    caller_phone: str
    from_number: str


class EndBody(BaseModel):
    ended_at: datetime
    outcome: Outcome
    duration_ms: int = Field(0, ge=0)
    # Optional upsert fields when /end arrives without a prior /start
    caller_phone: str = ""
    from_number: str = ""


class SummaryBody(BaseModel):
    summary: str


@router.post("/calls/{call_sid}/start", status_code=202)
async def call_start(request: Request, call_sid: str, body: StartBody) -> dict[str, Any]:
    state = get_state(request)
    state.call_store.record_call_start(
        Call(
            call_sid=call_sid,
            started_at=body.started_at,
            caller_phone=body.caller_phone,
            from_number=body.from_number,
        )
    )
    return {"ok": True}


@router.post("/calls/{call_sid}/end", status_code=202)
async def call_end(request: Request, call_sid: str, body: EndBody) -> dict[str, Any]:
    state = get_state(request)
    # Upsert parent doc if /start was never received
    existing = state.call_store.get_call(call_sid)
    if existing is None:
        state.call_store.record_call_start(
            Call(
                call_sid=call_sid,
                started_at=body.ended_at,  # best-effort: collapse start = end
                caller_phone=body.caller_phone or "+0",
                from_number=body.from_number or "+0",
            )
        )
    state.call_store.record_call_end(
        call_sid=call_sid,
        ended_at=body.ended_at,
        outcome=body.outcome,
        duration_ms=body.duration_ms,
    )
    return {"ok": True}


@router.post("/calls/{call_sid}/summary", status_code=202)
async def call_summary(request: Request, call_sid: str, body: SummaryBody) -> dict[str, Any]:
    state = get_state(request)
    state.call_store.set_summary(call_sid=call_sid, summary=body.summary)
    return {"ok": True}
