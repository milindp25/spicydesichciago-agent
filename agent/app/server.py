from __future__ import annotations

import json
import logging
from xml.sax.saxutils import quoteattr

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import PlainTextResponse

from app.bot import run_bot
from app.config import AgentSettings
from app.escalation import decode_chain, encode_chain, pop_head
from app.security.twilio_signature import TwilioSignatureVerifier

log = logging.getLogger(__name__)


# Map DTMF digit -> language code. 1=en, 2=hi, 3=te. Anything else -> en.
_DIGIT_TO_LANGUAGE: dict[str, str] = {"1": "en", "2": "hi", "3": "te"}


def _connect_stream_twiml(host: str, from_param: str, language: str) -> str:
    """Build the <Connect><Stream> TwiML, passing caller phone + language
    through to the Pipecat side via Stream <Parameter> elements (read on the
    start event)."""
    params: list[str] = []
    if from_param:
        params.append(f"      <Parameter name=\"from\" value={quoteattr(from_param)}/>")
    params.append(f"      <Parameter name=\"language\" value={quoteattr(language)}/>")
    params_xml = "\n".join(params) + "\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <Stream url="wss://{host}/twilio/stream">\n'
        f"{params_xml}"
        "    </Stream>\n"
        "  </Connect>\n"
        "</Response>"
    )


def _dtmf_gather_twiml(host: str) -> str:
    """Build the DTMF language-selection TwiML. The prompt uses plain Latin
    transliteration for Hindi/Telugu so Twilio's en-US <Say> can pronounce it
    cleanly without an IPA/voice-language swap.

    On timeout (no digit), <Redirect> falls through to /twilio/inbound-language
    with Digits=1, defaulting to English.
    """
    del host  # host not needed at the gather step — action is path-relative.
    prompt = (
        "Welcome to Spicy Desi. For English, press 1. "
        "Hindi ke liye, 2 dabaen. Telugu kosam, 3 nokkandi. "
        "Or stay on the line for English."
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        '  <Gather numDigits="1" timeout="3" '
        'action="/twilio/inbound-language" method="POST">\n'
        f'    <Say voice="alice" language="en-US">{prompt}</Say>\n'
        "  </Gather>\n"
        '  <Redirect method="POST">/twilio/inbound-language?Digits=1</Redirect>\n'
        "</Response>"
    )


def _full_url(request: Request) -> str:
    """Reconstruct the absolute URL Twilio signed.

    Behind Fly's TLS-terminating proxy, Uvicorn must run with
    --proxy-headers so request.url.scheme reflects X-Forwarded-Proto;
    otherwise this returns http:// and signature verification fails.
    """
    scheme = request.url.scheme
    host = request.headers.get("host", "")
    path = request.url.path
    query = request.url.query
    if query:
        return f"{scheme}://{host}{path}?{query}"
    return f"{scheme}://{host}{path}"


def build_app(settings: AgentSettings) -> FastAPI:
    app = FastAPI(title="Spicy Desi Agent")
    verifier = TwilioSignatureVerifier(auth_token=settings.twilio_auth_token)

    if not verifier.is_enabled():
        if settings.app_env == "production":
            raise RuntimeError(
                "TWILIO_AUTH_TOKEN is required in production: "
                "refusing to boot with signature verification disabled"
            )
        log.warning(
            "TWILIO_AUTH_TOKEN unset - Twilio signature verification DISABLED (dev mode)"
        )

    async def _verify_twilio(request: Request) -> None:
        form = await request.form()
        form_dict = {k: str(v) for k, v in form.items()}
        sig = request.headers.get("X-Twilio-Signature")
        if not verifier.verify(url=_full_url(request), form=form_dict, signature=sig):
            raise HTTPException(status_code=403, detail="invalid twilio signature")

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/twilio/inbound")
    async def twilio_inbound(request: Request) -> PlainTextResponse:
        await _verify_twilio(request)
        form = await request.form()
        from_phone = form.get("From")
        host = request.headers.get("host", "")
        from_param = (str(from_phone) if from_phone else "").strip()

        enabled = settings.languages_enabled or ["en"]
        if len(enabled) <= 1:
            # Single-language deploy: skip the DTMF gather entirely and pass
            # the lone configured language straight through.
            return PlainTextResponse(
                _connect_stream_twiml(host, from_param, language=enabled[0]),
                media_type="application/xml",
            )
        # Multi-language: play the DTMF gather. The from-number is dropped
        # at this hop (Twilio doesn't carry it through Gather), which is fine
        # because /twilio/inbound-language re-receives From in its form post.
        return PlainTextResponse(_dtmf_gather_twiml(host), media_type="application/xml")

    @app.post("/twilio/inbound-language")
    async def twilio_inbound_language(request: Request) -> PlainTextResponse:
        await _verify_twilio(request)
        form = await request.form()
        digit = str(form.get("Digits") or "").strip()
        from_phone = form.get("From")
        host = request.headers.get("host", "")
        from_param = (str(from_phone) if from_phone else "").strip()

        enabled = settings.languages_enabled or ["en"]
        # Map the digit to a language. Unknown/empty digit -> English.
        language = _DIGIT_TO_LANGUAGE.get(digit, "en")
        # If the caller asked for a language we don't have enabled, fall back
        # to the first enabled language (typically English).
        if language not in enabled:
            language = enabled[0]

        return PlainTextResponse(
            _connect_stream_twiml(host, from_param, language=language),
            media_type="application/xml",
        )

    def _take_message_twiml(host: str, say: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f"  <Say>{say}</Say>\n"
            "  <Connect>\n"
            f'    <Stream url="wss://{host}/twilio/stream"/>\n'
            "  </Connect>\n"
            "</Response>"
        )

    def _hangup_twiml() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response><Hangup/></Response>"
        )

    def _dial_next_twiml(head: dict, tail_encoded: str, say: str | None) -> str:
        """Build a TwiML <Dial> that hands off to escalation-fallback with the
        remaining chain encoded in the action URL.
        """
        phone = quoteattr(str(head["phone"])).strip('"')
        timeout = int(head.get("timeout_seconds", 25))
        # tail_encoded is already URL-safe base64 with no padding -> no escaping needed.
        action = f"/twilio/escalation-fallback?chain={tail_encoded}"
        say_block = f"  <Say>{say}</Say>\n" if say else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f"{say_block}"
            f'  <Dial timeout="{timeout}" action={quoteattr(action)}>{phone}</Dial>\n'
            "</Response>"
        )

    @app.post("/twilio/dial-owner")
    async def dial_owner(
        request: Request,
        to: str = Query(...),
        chain: str = Query(""),
    ) -> PlainTextResponse:
        await _verify_twilio(request)
        # Forward the escalation chain through the action URL so the fallback
        # can pop and dial the next contact on failure. Empty/absent chain
        # is fine — fallback degrades to today's take-message behavior.
        action_qs = f"?chain={chain}" if chain else ""
        action = f"/twilio/dial-owner-fallback{action_qs}"
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f'  <Dial timeout="25" action={quoteattr(action)}>{to}</Dial>\n'
            "</Response>"
        )
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.post("/twilio/dial-owner-fallback")
    async def dial_owner_fallback(
        request: Request,
        chain: str = Query(""),
    ) -> PlainTextResponse:
        await _verify_twilio(request)
        form = await request.form()
        dial_call_status = str(form.get("DialCallStatus") or "").lower()
        host = request.headers.get("host", "")
        log.info(
            "dial-owner-fallback fired",
            extra={"dial_call_status": dial_call_status, "chain_present": bool(chain)},
        )

        # Caller and owner finished a normal conversation -> just hang up.
        if dial_call_status == "completed":
            return PlainTextResponse(_hangup_twiml(), media_type="application/xml")

        # Try the next contact in the chain before taking a message.
        contacts = decode_chain(chain)
        head, tail = pop_head(contacts)
        if head is not None:
            label = head.get("label") or "backup"
            say = f"Owner didn't pick up - trying our {label} now."
            tail_encoded = encode_chain(tail)
            return PlainTextResponse(
                _dial_next_twiml(head, tail_encoded, say),
                media_type="application/xml",
            )

        # Chain exhausted (or empty) — fall through to take-message.
        if dial_call_status in ("failed", "canceled"):
            say = (
                "Hmm, looks like that number's not reachable. "
                "Let me grab a message for the owner instead."
            )
        elif dial_call_status == "busy":
            say = "Owner's on another call. Let me take a message and they'll ring you back."
        else:  # no-answer or anything else
            say = "Owner didn't pick up. Let me take a message and they'll ring you back."

        return PlainTextResponse(_take_message_twiml(host, say), media_type="application/xml")

    @app.post("/twilio/escalation-fallback")
    async def escalation_fallback(
        request: Request,
        chain: str = Query(""),
    ) -> PlainTextResponse:
        await _verify_twilio(request)
        form = await request.form()
        dial_call_status = str(form.get("DialCallStatus") or "").lower()
        host = request.headers.get("host", "")
        log.info(
            "escalation-fallback fired",
            extra={"dial_call_status": dial_call_status, "chain_present": bool(chain)},
        )

        # Caller and the escalation contact finished a normal conversation.
        if dial_call_status == "completed":
            return PlainTextResponse(_hangup_twiml(), media_type="application/xml")

        # Try the next contact in the remaining chain.
        contacts = decode_chain(chain)
        head, tail = pop_head(contacts)
        if head is not None:
            label = head.get("label") or "backup"
            say = f"Still trying — let me ring our {label}."
            tail_encoded = encode_chain(tail)
            return PlainTextResponse(
                _dial_next_twiml(head, tail_encoded, say),
                media_type="application/xml",
            )

        # Chain exhausted — fall through to take-message.
        if dial_call_status in ("failed", "canceled"):
            say = (
                "Hmm, that didn't go through either. "
                "Let me grab a message for the owner instead."
            )
        elif dial_call_status == "busy":
            say = "They're on another call too. Let me take a message and they'll ring you back."
        else:
            say = "No answer there either. Let me take a message and they'll ring you back."

        return PlainTextResponse(_take_message_twiml(host, say), media_type="application/xml")

    @app.websocket("/twilio/stream")
    async def twilio_stream(ws: WebSocket) -> None:
        await ws.accept()

        stream_sid: str | None = None
        call_sid: str | None = None
        from_phone: str = ""
        language: str = "en"
        for _ in range(3):
            msg = await ws.receive_text()
            data = json.loads(msg)
            if data.get("event") == "start":
                start = data["start"]
                stream_sid = start["streamSid"]
                call_sid = start.get("callSid", "")
                custom = start.get("customParameters") or {}
                from_phone = (custom.get("from") or "").strip()
                language = (custom.get("language") or "en").strip() or "en"
                break

        if not stream_sid:
            log.warning("twilio stream did not deliver a start event; closing")
            await ws.close()
            return

        log.info(
            "twilio stream started",
            extra={
                "stream_sid": stream_sid,
                "call_sid": call_sid,
                "from": from_phone,
                "language": language,
            },
        )
        await run_bot(
            ws,
            settings=settings,
            stream_sid=stream_sid,
            call_sid=call_sid or "",
            from_phone=from_phone,
            language=language,
        )

    return app
