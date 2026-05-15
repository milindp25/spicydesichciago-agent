from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/callers/history")
async def caller_history(
    request: Request,
    phone: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """Return a brief history of prior interactions for a given caller.

    Used by the agent at call start so it can greet returning customers
    differently. Backed by /callers/{phone} aggregate + most recent
    events from their most recent call.
    """
    _ = limit  # reserved for future use (event paging); aggregate is single doc today
    state = get_state(request)
    caller = state.caller_store.get(phone)
    if caller is None:
        return {
            "phone": phone,
            "is_returning": False,
            "call_count": 0,
            "events": [],
        }
    events: list[dict[str, Any]] = []
    if caller.last_call_sid:
        for ev in state.call_store.iter_events(caller.last_call_sid):
            events.append(
                {
                    "ts": ev.ts.timestamp(),
                    "kind": ev.kind,
                    "call_sid": caller.last_call_sid,
                    "summary": _short_summary(ev.kind, ev.payload),
                }
            )
    return {
        "phone": phone,
        "is_returning": True,
        "call_count": caller.call_count,
        "events": events,
    }


def _short_summary(kind: str, payload: dict[str, Any]) -> str:
    if kind == "messageTaken":
        return f"Left a message: {(payload.get('reason') or '')[:80]}"
    if kind == "transferInitiated":
        return "Asked to be transferred"
    if kind == "smsLinkSent":
        return f"Sent {payload.get('kind')} link via SMS"
    if kind == "callStarted":
        return "Called previously"
    return kind
