from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


def _matches_phone(payload: dict[str, Any], phone: str) -> bool:
    """Check whether an event payload references the given phone number."""
    return any(payload.get(key) == phone for key in ("from_phone", "callback_number", "to"))


@router.get("/callers/history")
async def caller_history(
    request: Request,
    phone: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """Return a brief history of prior interactions for a given caller phone.

    Used by the agent at call start so it can greet returning customers
    differently and recall outstanding messages.
    """
    state = get_state(request)
    events = await state.event_log.read_all()
    matches = []
    for ev in reversed(events):  # newest first
        payload = ev.get("payload") or {}
        if _matches_phone(payload, phone) or ev.get("from_phone") == phone:
            matches.append(
                {
                    "ts": ev.get("ts"),
                    "kind": ev.get("kind"),
                    "call_sid": ev.get("call_sid"),
                    "summary": _short_summary(ev),
                }
            )
            if len(matches) >= limit:
                break
    return {
        "phone": phone,
        "is_returning": len(matches) > 0,
        "call_count": len({m["call_sid"] for m in matches if m["call_sid"]}),
        "events": matches,
    }


def _short_summary(ev: dict[str, Any]) -> str:
    kind = ev.get("kind", "")
    payload = ev.get("payload") or {}
    if kind == "message_taken":
        return f"Left a message: {payload.get('reason', '')[:80]}"
    if kind == "transfer_decided":
        decision = payload.get("decision") or {}
        return f"Transfer attempt ({decision.get('action', '?')})"
    if kind == "sms_link_sent":
        return f"Sent {payload.get('kind')} link via SMS"
    if kind == "call_started":
        return "Called previously"
    return kind
