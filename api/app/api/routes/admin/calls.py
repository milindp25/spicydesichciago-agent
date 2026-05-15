"""Dashboard calls endpoints: today's calls + call detail with events."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_admin_user
from app.domain.call import Call

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])


def _serialize_call(call_sid: str, call: Call) -> dict[str, Any]:
    return {
        "callSid": call_sid,
        "startedAt": call.started_at.isoformat() if call.started_at else None,
        "endedAt": call.ended_at.isoformat() if call.ended_at else None,
        "durationMs": call.duration_ms,
        "callerPhone": call.caller_phone,
        "fromNumber": call.from_number,
        "outcome": call.outcome.value,
        "summary": call.summary,
        "toolsUsed": list(call.tools_used),
    }


@router.get("/calls/today")
async def calls_today(request: Request) -> dict[str, list[dict[str, Any]]]:
    state = get_state(request)
    calls: list[dict[str, Any]] = []
    for call_sid, call in state.call_store.list_today_chicago(limit=200):
        calls.append(_serialize_call(call_sid, call))
    return {"calls": calls}


@router.get("/calls/{call_sid}")
async def call_detail(request: Request, call_sid: str) -> dict[str, Any]:
    state = get_state(request)
    call = state.call_store.get_call(call_sid)
    if call is None:
        raise HTTPException(status_code=404, detail="call not found")
    events: list[dict[str, Any]] = []
    for ev in state.call_store.iter_events(call_sid):
        events.append({
            "ts": ev.ts.isoformat() if ev.ts else None,
            "kind": ev.kind,
            "payload": dict(ev.payload),
        })
    return {"call": _serialize_call(call_sid, call), "events": events}


@router.get("/calls/{call_sid}/transcript")
async def call_transcript(request: Request, call_sid: str) -> dict[str, Any]:
    state = get_state(request)
    transcript = state.transcript_store.get(call_sid)
    if transcript is None:
        raise HTTPException(status_code=404, detail="transcript not found")
    return {
        "callSid": transcript.call_sid,
        "storedAt": transcript.stored_at.isoformat(),
        "turns": [{"role": t.role, "text": t.text} for t in transcript.turns],
    }
