from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import CallEvent, EventKind

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


class SmsLinkRequest(BaseModel):
    call_sid: str
    to: str = Field(..., min_length=1)  # E.164 caller number
    kind: Literal["order", "location"]


def _maps_url(address: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(address)


@router.post("/sms/send-link", status_code=202)
async def send_link(request: Request, body: SmsLinkRequest) -> dict[str, Any]:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")

    if body.kind == "order":
        if not tenant.order_url:
            raise HTTPException(409, "order_url not configured for tenant")
        sms_body = (
            f"Order from {tenant.name} here: {tenant.order_url}\n"
            "Thanks for calling!"
        )
        link = tenant.order_url
    else:  # location
        pickup = await state.pickup_service.get_today("spicy-desi")
        if pickup is None or not pickup.address:
            raise HTTPException(409, "no active pickup location with an address")
        sms_body = (
            f"{tenant.name} today: {pickup.name}\n"
            f"{pickup.address}\n"
            f"{_maps_url(pickup.address)}"
        )
        link = _maps_url(pickup.address)

    sms_sent = await state.twilio.send_sms(to=body.to, body=sms_body)

    state.call_store.append_event(
        call_sid=body.call_sid,
        event=CallEvent(
            ts=datetime.now(timezone.utc),
            kind=EventKind.SMS_LINK_SENT.value,
            payload={"to": body.to, "kind": body.kind, "sms_sent": sms_sent, "link": link},
        ),
        caller_phone_for_upsert=body.to or "+0",
        from_number_for_upsert="+0",
    )

    return {"ok": sms_sent, "kind": body.kind, "sent_to": body.to}
