from __future__ import annotations

from fastapi import FastAPI, Form, Request, WebSocket
from fastapi.responses import PlainTextResponse

from app.bot import run_bot
from app.config import AgentSettings


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
    async def dial_owner(to: str = Form(...)) -> PlainTextResponse:
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
        # Twilio sends a "start" event with call_sid in the first WS message.
        # The Pipecat Twilio serializer parses this; we pass through to run_bot
        # which delegates frame handling to the transport.
        call_sid = "PENDING"
        await run_bot(ws, settings=settings, call_sid=call_sid)

    return app
