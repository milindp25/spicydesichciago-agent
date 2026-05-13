"""Integration tests: /twilio/inbound must reject unsigned requests in production mode."""
from __future__ import annotations

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.config import AgentSettings
from app.server import build_app


def _settings_with_token(token: str) -> AgentSettings:
    """Build settings with required fields populated for tests."""
    return AgentSettings(
        TOOLS_API_BASE="http://test-api",
        TOOLS_SHARED_SECRET="x" * 32,
        GROQ_API_KEY="test",
        DEEPGRAM_API_KEY="test",
        CARTESIA_API_KEY="test",
        CARTESIA_VOICE_ID="test-voice",
        TWILIO_AUTH_TOKEN=token,
    )


def test_inbound_rejects_unsigned_when_token_set() -> None:
    app = build_app(_settings_with_token("real-auth-token-32-bytes-long-xx"))
    client = TestClient(app)
    resp = client.post("/twilio/inbound", data={"From": "+15551234567"})
    assert resp.status_code == 403


def test_inbound_accepts_valid_signature() -> None:
    token = "real-auth-token-32-bytes-long-xx"
    app = build_app(_settings_with_token(token))
    client = TestClient(app)

    form = {"From": "+15551234567"}
    url = "http://testserver/twilio/inbound"
    sig = RequestValidator(token).compute_signature(url, form)

    resp = client.post("/twilio/inbound", data=form, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<Stream" in resp.text


def test_inbound_accepts_anything_in_dev_mode() -> None:
    """Empty token = dev mode, anything goes."""
    app = build_app(_settings_with_token(""))
    client = TestClient(app)
    resp = client.post("/twilio/inbound", data={"From": "+15551234567"})
    assert resp.status_code == 200
    assert "<Stream" in resp.text
