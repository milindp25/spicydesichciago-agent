from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import AppState, get_state, require_tools_auth
from app.domain.call import CallEvent, EventKind
from app.domain.message import MessageStatus

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
            "last_summary": None,
            "last_message_reason": None,
            "last_message_pending": None,
            "last_sms_kind": None,
            "recent_menu_queries": [],
        }
    events: list[dict[str, Any]] = []
    raw_events: list[CallEvent] = []
    if caller.last_call_sid:
        for ev in state.call_store.iter_events(caller.last_call_sid):
            raw_events.append(ev)
            events.append(
                {
                    "ts": ev.ts.timestamp(),
                    "kind": ev.kind,
                    "call_sid": caller.last_call_sid,
                    "summary": _short_summary(ev.kind, ev.payload),
                }
            )

    last_summary = _last_summary(state, caller.last_call_sid)
    last_message_reason = _last_payload_field(
        raw_events, EventKind.MESSAGE_TAKEN.value, "reason"
    )
    last_message_pending = _last_message_pending(
        state, raw_events, caller.last_call_sid
    )
    last_sms_kind = _last_payload_field(
        raw_events, EventKind.SMS_LINK_SENT.value, "kind"
    )
    recent_menu_queries = _recent_menu_queries(raw_events)

    return {
        "phone": phone,
        "is_returning": True,
        "call_count": caller.call_count,
        "events": events,
        "last_summary": last_summary,
        "last_message_reason": last_message_reason,
        "last_message_pending": last_message_pending,
        "last_sms_kind": last_sms_kind,
        "recent_menu_queries": recent_menu_queries,
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


def _last_summary(state: AppState, last_call_sid: str | None) -> str | None:
    if not last_call_sid:
        return None
    call = state.call_store.get_call(last_call_sid)
    if call is None:
        return None
    return call.summary or None


def _last_payload_field(
    events: list[CallEvent], kind: str, field: str
) -> str | None:
    """Find the most recent event of `kind` (events arrive sorted by ts asc).
    Return payload[field] as str or None.
    """
    for ev in reversed(events):
        if ev.kind == kind:
            val = ev.payload.get(field)
            if val is None:
                return None
            return str(val)
    return None


def _last_message_pending(
    state: AppState,
    events: list[CallEvent],
    last_call_sid: str | None,
) -> bool | None:
    """Was the caller's most recent messageTaken still unhandled?

    Returns None if there's no messageTaken event for this call, or if the
    corresponding /messages/{id} doc cannot be located (older data).
    """
    if not last_call_sid:
        return None
    has_message_taken = any(
        ev.kind == EventKind.MESSAGE_TAKEN.value for ev in events
    )
    if not has_message_taken:
        return None
    msg = state.message_store.find_latest_by_call_sid(call_sid=last_call_sid)
    if msg is None:
        return None
    return msg.status == MessageStatus.NEW


def _recent_menu_queries(events: list[CallEvent]) -> list[str]:
    """Extract up to 3 distinct lowercased queries from search_menu toolCalled
    events. Preserve first-seen order (newest first because we iterate reversed).
    """
    out: list[str] = []
    seen: set[str] = set()
    for ev in reversed(events):
        if ev.kind != EventKind.TOOL_CALLED.value:
            continue
        payload = ev.payload or {}
        if payload.get("name") != "search_menu":
            continue
        args = payload.get("arguments") or payload.get("args") or {}
        query = args.get("query") if isinstance(args, dict) else None
        if not query:
            continue
        q = str(query).strip().lower()
        if not q or q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= 3:
            break
    return out
