from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Query, Request, WebSocket
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
    async def twilio_inbound(request: Request) -> PlainTextResponse:
        host = request.headers.get("host", "")
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            "  <Connect>\n"
            f'    <Stream url="wss://{host}/twilio/stream"/>\n'
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

        # Twilio sends a "connected" event followed by a "start" event with
        # streamSid and callSid. We need both before constructing the
        # TwilioFrameSerializer.
        stream_sid: str | None = None
        call_sid: str | None = None
        for _ in range(3):
            msg = await ws.receive_text()
            data = json.loads(msg)
            if data.get("event") == "start":
                start = data["start"]
                stream_sid = start["streamSid"]
                call_sid = start.get("callSid", "")
                break

        if not stream_sid:
            log.warning("twilio stream did not deliver a start event; closing")
            await ws.close()
            return

        log.info("twilio stream started", extra={"stream_sid": stream_sid, "call_sid": call_sid})
        await run_bot(
            ws,
            settings=settings,
            stream_sid=stream_sid,
            call_sid=call_sid or "",
        )

    return app
