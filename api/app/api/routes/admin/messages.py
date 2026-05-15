"""Dashboard messages endpoints: list unhandled + mark handled."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_admin_user

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])


@router.get("/messages/unhandled")
async def unhandled_messages(request: Request) -> dict[str, list[dict[str, Any]]]:
    state = get_state(request)
    msgs: list[dict[str, Any]] = []
    for msg_id, m in state.message_store.list_unhandled(limit=200):
        msgs.append(
            {
                "id": msg_id,
                "callSid": m.call_sid,
                "callerPhone": m.caller_phone,
                "callerName": m.caller_name,
                "reason": m.reason,
                "takenAt": m.taken_at.isoformat() if m.taken_at else None,
            }
        )
    return {"messages": msgs}


@router.post("/messages/{message_id}/handle")
async def handle_message(
    request: Request,
    message_id: str,
    user: dict = Depends(require_admin_user),
) -> dict[str, Any]:
    state = get_state(request)
    if state.message_store.get(message_id) is None:
        raise HTTPException(status_code=404, detail="message not found")
    state.message_store.mark_handled(
        message_id=message_id,
        handled_at=datetime.now(timezone.utc),
        handled_by=user["uid"],
    )
    return {"ok": True, "status": "handled"}
