from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import CallEvent, EventKind
from app.domain.models import EscalationContact, TransferRequest
from app.services.transfer_decision_service import decide_transfer


def _encode_escalation_chain(contacts: list[EscalationContact]) -> str:
    """URL-safe base64 JSON of the escalation chain. Empty for empty list.

    Mirrors the encoding accepted by the agent's `app.escalation.decode_chain`
    so the agent stays stateless on tenant config.
    """
    if not contacts:
        return ""
    payload = [
        {
            "phone": c.phone,
            "timeout_seconds": c.timeout_seconds,
            "label": c.label,
        }
        for c in contacts
    ]
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/transfers")
async def request_transfer(
    request: Request, body: TransferRequest, now: str | None = Query(None)
) -> dict[str, Any]:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else None
    decision = decide_transfer(
        tenant, now=now_dt, owner_override_store=state.owner_override_store
    )

    redirect_ok = False
    if decision.action == "transfer" and state.agent_public_url:
        twiml_url = f"{state.agent_public_url}/twilio/dial-owner?to={tenant.owner_phone}"
        # Append the escalation chain so the agent can fall through to backup
        # contacts on owner-dial failure before taking a message.
        chain = _encode_escalation_chain(tenant.escalation)
        if chain:
            twiml_url = f"{twiml_url}&chain={chain}"
        redirect_ok = await state.twilio.redirect_call(call_sid=body.call_sid, twiml_url=twiml_url)

    state.call_store.append_event(
        call_sid=body.call_sid,
        event=CallEvent(
            ts=datetime.now(timezone.utc),
            kind=EventKind.TRANSFER_DECIDED.value,
            payload={
                "decision": decision.model_dump(),
                "reason": body.reason,
                "redirect_ok": redirect_ok,
            },
        ),
        caller_phone_for_upsert="+0",
        from_number_for_upsert="+0",
    )

    return {**decision.model_dump(), "redirect_ok": redirect_ok}
