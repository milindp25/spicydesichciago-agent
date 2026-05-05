from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Form, Query, Request, WebSocket
from fastapi.responses import PlainTextResponse

from app.bot import run_bot
from app.config import AgentSettings

log = logging.getLogger(__name__)


def build_app(settings: AgentSettings) -> FastAPI:
    app = FastAPI(title="Spicy Desi Agent")

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/twilio/inbound")
    async def twilio_inbound(
        request: Request,
        from_phone: str | None = Form(None, alias="From"),
    ) -> PlainTextResponse:
        host = request.headers.get("host", "")
        # Pass the caller's phone number through to the WebSocket via a
        # Twilio Stream <Parameter>. The Pipecat side reads this from the
        # `start` event's customParameters.
        from_param = (from_phone or "").strip()
        param_xml = f'    <Parameter name="from" value="{from_param}"/>\n' if from_param else ""
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            "  <Connect>\n"
            f'    <Stream url="wss://{host}/twilio/stream">\n'
            f"{param_xml}"
            "    </Stream>\n"
            "  </Connect>\n"
            "</Response>"
        )
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.post("/twilio/dial-owner")
    async def dial_owner(to: str = Query(...)) -> PlainTextResponse:
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f'  <Dial timeout="25" action="/twilio/dial-owner-fallback">{to}</Dial>\n'
            "</Response>"
        )
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.post("/twilio/dial-owner-fallback")
    async def dial_owner_fallback(
        request: Request,
        DialCallStatus: str | None = Form(None),  # noqa: N803
    ) -> PlainTextResponse:
        host = request.headers.get("host", "")
        status = (DialCallStatus or "").lower()
        log.info("dial-owner-fallback fired", extra={"DialCallStatus": status})

        # Caller and owner finished a normal conversation -> just hang up.
        if status == "completed":
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<Response><Hangup/></Response>"
            )
            return PlainTextResponse(twiml, media_type="application/xml")

        # Phrasing depends on why the dial failed.
        if status in ("failed", "canceled"):
            say = (
                "Hmm, looks like that number's not reachable. "
                "Let me grab a message for the owner instead."
            )
        elif status == "busy":
            say = "Owner's on another call. Let me take a message and they'll ring you back."
        else:  # no-answer or anything else
            say = "Owner didn't pick up. Let me take a message and they'll ring you back."

        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f"  <Say>{say}</Say>\n"
            "  <Connect>\n"
            f'    <Stream url="wss://{host}/twilio/stream"/>\n'
            "  </Connect>\n"
            "</Response>"
        )
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.websocket("/twilio/stream")
    async def twilio_stream(ws: WebSocket) -> None:
        await ws.accept()

        stream_sid: str | None = None
        call_sid: str | None = None
        from_phone: str = ""
        for _ in range(3):
            msg = await ws.receive_text()
            data = json.loads(msg)
            if data.get("event") == "start":
                start = data["start"]
                stream_sid = start["streamSid"]
                call_sid = start.get("callSid", "")
                custom = start.get("customParameters") or {}
                from_phone = (custom.get("from") or "").strip()
                break

        if not stream_sid:
            log.warning("twilio stream did not deliver a start event; closing")
            await ws.close()
            return

        log.info(
            "twilio stream started",
            extra={"stream_sid": stream_sid, "call_sid": call_sid, "from": from_phone},
        )
        await run_bot(
            ws,
            settings=settings,
            stream_sid=stream_sid,
            call_sid=call_sid or "",
            from_phone=from_phone,
        )

    return app
