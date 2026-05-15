"""Owner-initiated callback flow.

Three routes, all unauthenticated — the signed callback token IS the auth.

- GET  /api/callback/{token}         HTML view with a "Call now" button.
- POST /api/callback/{token}/start   Initiates an outbound call to the owner.
- POST /api/callback/{token}/twiml   Twilio fetches this when the owner answers;
                                     returns TwiML that <Dial>s the original caller.
"""

from __future__ import annotations

import html
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.api.dependencies import get_state
from app.services.callback_tokens import decode as decode_callback_token

router = APIRouter(prefix="/api/callback")


def _require_enabled(state) -> None:
    if not state.callback_token_secret:
        raise HTTPException(status_code=503, detail="callback service disabled")


def _gone(message: str) -> HTMLResponse:
    body = (
        "<!doctype html><html><body style='font-family:system-ui;padding:2rem;max-width:32rem'>"
        f"<h1>Link expired</h1><p>{html.escape(message)}</p>"
        "<p>Ask the customer to call back, or text them directly.</p>"
        "</body></html>"
    )
    return HTMLResponse(body, status_code=410)


@router.get("/{token}", response_class=HTMLResponse)
async def callback_view(token: str, request: Request) -> HTMLResponse:
    state = get_state(request)
    _require_enabled(state)
    try:
        payload = decode_callback_token(token, secret=state.callback_token_secret)
    except ValueError as e:
        return _gone(str(e))

    caller_phone = str(payload.get("caller_phone", ""))
    message_id = str(payload.get("message_id", ""))
    safe_caller = html.escape(caller_phone)
    safe_msg = html.escape(message_id)
    safe_token = html.escape(token)
    body = (
        "<!doctype html><html><body style='font-family:system-ui;padding:2rem;max-width:32rem'>"
        "<h1>Spicy Desi callback</h1>"
        f"<p>Call back <strong>{safe_caller}</strong>?</p>"
        f"<p style='color:#666'>Message id: {safe_msg}</p>"
        f"<form method='POST' action='/api/callback/{safe_token}/start'>"
        f"<button type='submit' style='font-size:1.25rem;padding:0.75rem 1.5rem'>"
        f"Call {safe_caller} now</button>"
        "</form>"
        "<p style='color:#666;font-size:0.85rem'>"
        "We will call your phone first; pick up to be connected to the caller."
        "</p></body></html>"
    )
    return HTMLResponse(body)


@router.post("/{token}/start", response_class=HTMLResponse)
async def callback_start(token: str, request: Request) -> HTMLResponse:
    state = get_state(request)
    _require_enabled(state)
    try:
        payload = decode_callback_token(token, secret=state.callback_token_secret)
    except ValueError as e:
        return _gone(str(e))

    owner_phone = str(payload.get("owner_phone", ""))
    caller_phone = str(payload.get("caller_phone", ""))

    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    from_number = (tenant.twilio_number or "").strip()
    if not from_number:
        return HTMLResponse(
            "<!doctype html><html><body><h1>Cannot place call</h1>"
            "<p>Tenant Twilio number is not configured.</p></body></html>",
            status_code=503,
        )

    public_url = (state.callback_public_url or "").rstrip("/")
    twiml_url = f"{public_url}/api/callback/{token}/twiml"

    sid = await state.twilio.create_call(to=owner_phone, from_=from_number, url=twiml_url)
    if not sid:
        return HTMLResponse(
            "<!doctype html><html><body style='font-family:system-ui;padding:2rem'>"
            "<h1>Could not start callback</h1>"
            "<p>Twilio failed to initiate the call. Try again, or dial directly: "
            f"<a href='tel:{html.escape(caller_phone)}'>{html.escape(caller_phone)}</a>.</p>"
            "</body></html>",
            status_code=502,
        )
    return HTMLResponse(
        "<!doctype html><html><body style='font-family:system-ui;padding:2rem;max-width:32rem'>"
        "<h1>Calling you back now</h1>"
        f"<p>Pick up to connect to <strong>{html.escape(caller_phone)}</strong>.</p>"
        "</body></html>"
    )


@router.post("/{token}/twiml")
async def callback_twiml(token: str, request: Request) -> Response:
    state = get_state(request)
    _require_enabled(state)
    try:
        payload = decode_callback_token(token, secret=state.callback_token_secret)
    except ValueError:
        # Return a polite hangup; Twilio is the only legitimate consumer.
        return Response(
            "<?xml version='1.0' encoding='UTF-8'?><Response><Hangup/></Response>",
            media_type="application/xml",
        )
    caller_phone = str(payload.get("caller_phone", ""))
    twiml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<Response><Dial><Number>{xml_escape(caller_phone)}</Number></Dial></Response>"
    )
    return Response(twiml, media_type="application/xml")
