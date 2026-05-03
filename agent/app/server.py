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
    async def dial_owner_fallback(request: Request) -> PlainTextResponse:
        host = request.headers.get("host", "")
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            "  <Say>The owner couldn't pick up. Let me take a message instead.</Say>\n"
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
