from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AgentSettings
from app.server import build_app


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOLS_API_BASE", "http://localhost:8080")
    monkeypatch.setenv("TOOLS_SHARED_SECRET", "s" * 32)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "test-voice")


def _client(monkeypatch: pytest.MonkeyPatch, languages: str | None = None) -> TestClient:
    _base_env(monkeypatch)
    if languages is not None:
        monkeypatch.setenv("AGENT_LANGUAGES_ENABLED", languages)
    settings = AgentSettings()
    return TestClient(build_app(settings))


def test_inbound_single_language_skips_gather(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch)  # default = en only
    r = c.post("/twilio/inbound", headers={"Host": "agent.example.com"})
    assert r.status_code == 200
    body = r.text
    assert "<Gather" not in body
    assert "<Connect>" in body
    assert '<Stream url="wss://agent.example.com/twilio/stream"' in body
    assert '<Parameter name="language" value="en"/>' in body


def test_inbound_multi_language_plays_gather(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch, languages="en,hi,te")
    r = c.post("/twilio/inbound", headers={"Host": "agent.example.com"})
    assert r.status_code == 200
    body = r.text
    assert "<Gather" in body
    assert 'action="/twilio/inbound-language"' in body
    assert 'numDigits="1"' in body
    assert "press 1" in body
    # Timeout fallback redirects to inbound-language with Digits=1 (English).
    assert "/twilio/inbound-language?Digits=1" in body


def test_inbound_language_digit_1_is_english(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch, languages="en,hi,te")
    r = c.post(
        "/twilio/inbound-language",
        data={"Digits": "1", "From": "+15555550123"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert '<Stream url="wss://agent.example.com/twilio/stream"' in body
    assert '<Parameter name="language" value="en"/>' in body
    assert '<Parameter name="from" value="+15555550123"/>' in body


def test_inbound_language_digit_2_is_hindi(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch, languages="en,hi,te")
    r = c.post(
        "/twilio/inbound-language",
        data={"Digits": "2"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    assert '<Parameter name="language" value="hi"/>' in r.text


def test_inbound_language_digit_3_is_telugu(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch, languages="en,hi,te")
    r = c.post(
        "/twilio/inbound-language",
        data={"Digits": "3"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    assert '<Parameter name="language" value="te"/>' in r.text


def test_inbound_language_fallback_when_target_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hindi NOT enabled — pressing 2 should fall back to the first enabled
    # language (English).
    c = _client(monkeypatch, languages="en")
    r = c.post(
        "/twilio/inbound-language",
        data={"Digits": "2"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    assert '<Parameter name="language" value="en"/>' in r.text


def test_inbound_language_no_digits_is_english(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch, languages="en,hi,te")
    r = c.post(
        "/twilio/inbound-language",
        data={},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    assert '<Parameter name="language" value="en"/>' in r.text


def test_inbound_language_invalid_digit_is_english(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch, languages="en,hi,te")
    r = c.post(
        "/twilio/inbound-language",
        data={"Digits": "9"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    assert '<Parameter name="language" value="en"/>' in r.text
