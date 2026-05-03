from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AgentSettings
from app.server import build_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TOOLS_API_BASE", "http://localhost:8080")
    monkeypatch.setenv("TOOLS_SHARED_SECRET", "s" * 32)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "test-voice")
    settings = AgentSettings()
    return TestClient(build_app(settings))


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_twilio_inbound_returns_twiml_with_stream_url(client: TestClient) -> None:
    r = client.post("/twilio/inbound", headers={"Host": "agent.example.com"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    body = r.text
    assert "<Connect>" in body
    assert '<Stream url="wss://agent.example.com/twilio/stream"' in body


def test_dial_owner_returns_twiml_dial(client: TestClient) -> None:
    r = client.post("/twilio/dial-owner", data={"to": "+15555550199"})
    assert r.status_code == 200
    body = r.text
    assert "<Dial " in body
    assert "+15555550199</Dial>" in body
    assert 'action="/twilio/dial-owner-fallback"' in body


def test_dial_owner_fallback_streams_back_to_agent(client: TestClient) -> None:
    r = client.post("/twilio/dial-owner-fallback", headers={"Host": "agent.example.com"})
    assert r.status_code == 200
    body = r.text
    assert "<Say>" in body
    assert '<Stream url="wss://agent.example.com/twilio/stream"' in body
