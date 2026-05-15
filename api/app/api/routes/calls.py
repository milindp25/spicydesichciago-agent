"""POST /api/calls/{sid}/start, /end, /summary — call lifecycle endpoints
used by the agent. Writes to FirestoreCallStore.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import Call, Outcome
from app.domain.transcript import Turn

MAX_TURNS = 200
MAX_TURN_CHARS = 1000

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


class TranscriptTurnIn(BaseModel):
    role: Literal["caller", "agent"]
    text: str


class TranscriptBody(BaseModel):
    turns: list[TranscriptTurnIn] = Field(default_factory=list)


@router.post("/calls/{call_sid}/transcript", status_code=202)
async def call_transcript(
    request: Request, call_sid: str, body: TranscriptBody
) -> dict[str, Any]:
    if not body.turns:
        raise HTTPException(status_code=400, detail="turns must be non-empty")
    if len(body.turns) > MAX_TURNS:
        raise HTTPException(
            status_code=400, detail=f"too many turns (max {MAX_TURNS})"
        )
    cleaned: list[Turn] = []
    for t in body.turns:
        text = t.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="turn text must be non-empty")
        if len(text) > MAX_TURN_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"turn text exceeds {MAX_TURN_CHARS} chars",
            )
        cleaned.append(Turn(role=t.role, text=text))

    state = get_state(request)
    state.transcript_store.set(
        call_sid=call_sid,
        turns=cleaned,
        stored_at=datetime.now(timezone.utc),
    )
    return {"ok": True, "turn_count": len(cleaned)}


@router.post("/calls/{call_sid}/summary", status_code=202)
async def call_summary(request: Request, call_sid: str, body: SummaryBody) -> dict[str, Any]:
    state = get_state(request)
    state.call_store.set_summary(call_sid=call_sid, summary=body.summary)
    return {"ok": True}
