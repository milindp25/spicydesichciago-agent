from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, Any]:
    """Aggregate counters from the JSONL event log.

    Cheap to compute against today's volumes; if call traffic grows we'll
    move this to a proper time-series store. Counts are over the entire
    log file — caller decides any windowing client-side.
    """
    state = get_state(request)
    events = await state.event_log.read_all()

    by_kind: dict[str, int] = defaultdict(int)
    call_starts: dict[str, float] = {}
    call_durations: list[float] = []
    transfers_attempted = 0
    transfers_succeeded = 0
    tool_errors = 0
    unique_calls: set[str] = set()

    for ev in events:
        kind = ev.get("kind") or ""
        sid = ev.get("call_sid") or ""
        ts = ev.get("ts")
        by_kind[kind] += 1
        if sid:
            unique_calls.add(sid)
        if kind == "call_started" and ts and sid:
            call_starts[sid] = ts
        elif kind == "call_ended" and ts and sid and sid in call_starts:
            call_durations.append(ts - call_starts.pop(sid))
        elif kind == "transfer_decided":
            payload = ev.get("payload") or {}
            decision = payload.get("decision") or {}
            if decision.get("action") == "transfer":
                transfers_attempted += 1
                if payload.get("redirect_ok"):
                    transfers_succeeded += 1
        elif kind == "tool_error":
            tool_errors += 1

    avg_dur = (sum(call_durations) / len(call_durations)) if call_durations else 0.0
    return {
        "total_events": len(events),
        "unique_calls": len(unique_calls),
        "events_by_kind": dict(by_kind),
        "calls_with_duration": len(call_durations),
        "avg_call_seconds": round(avg_dur, 1),
        "transfers_attempted": transfers_attempted,
        "transfers_succeeded": transfers_succeeded,
        "tool_errors": tool_errors,
    }
