"""Integration tests for escalation-chain TwiML routes.

These tests rely on dev-mode signature bypass: `TWILIO_AUTH_TOKEN` is unset
so `TwilioSignatureVerifier` reports `is_enabled() == False` and accepts
all requests. This matches the pattern used by `test_server_routes.py`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AgentSettings
from app.escalation import decode_chain, encode_chain
from app.server import build_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TOOLS_API_BASE", "http://localhost:8080")
    monkeypatch.setenv("TOOLS_SHARED_SECRET", "s" * 32)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "test-voice")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    settings = AgentSettings()
    return TestClient(build_app(settings))


def test_dial_owner_includes_chain_in_action_when_provided(client: TestClient) -> None:
    chain = encode_chain(
        [{"phone": "+13125550100", "timeout_seconds": 25, "label": "manager"}]
    )
    r = client.post(f"/twilio/dial-owner?to=%2B15551112222&chain={chain}")
    assert r.status_code == 200
    body = r.text
    assert "<Dial " in body
    # action URL forwards the chain.
    assert f"/twilio/dial-owner-fallback?chain={chain}" in body


def test_dial_owner_action_has_no_chain_when_absent(client: TestClient) -> None:
    r = client.post("/twilio/dial-owner?to=%2B15551112222")
    assert r.status_code == 200
    body = r.text
    # Backward-compatible: no chain query param appended.
    assert 'action="/twilio/dial-owner-fallback"' in body
    assert "chain=" not in body


def test_dial_owner_fallback_with_chain_dials_next(client: TestClient) -> None:
    chain = encode_chain(
        [{"phone": "+13125550100", "timeout_seconds": 30, "label": "manager"}]
    )
    r = client.post(
        f"/twilio/dial-owner-fallback?chain={chain}",
        data={"DialCallStatus": "no-answer"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "<Dial " in body
    assert "timeout=\"30\"" in body
    assert "+13125550100</Dial>" in body
    # Action URL points to escalation-fallback. With one contact, remaining
    # chain after pop is empty -> chain param empty/absent.
    assert "/twilio/escalation-fallback?chain=" in body
    # The remaining chain should be empty (single-element list popped).
    import re

    m = re.search(r'action="(/twilio/escalation-fallback\?chain=[^"]*)"', body)
    assert m is not None
    next_action = m.group(1)
    next_chain = next_action.split("chain=", 1)[1]
    assert decode_chain(next_chain) == []


def test_dial_owner_fallback_no_chain_falls_through_to_take_message(
    client: TestClient,
) -> None:
    r = client.post(
        "/twilio/dial-owner-fallback",
        data={"DialCallStatus": "no-answer"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "<Say>" in body
    assert "Owner didn't pick up" in body
    assert '<Stream url="wss://agent.example.com/twilio/stream"' in body


def test_dial_owner_fallback_completed_hangs_up_even_with_chain(client: TestClient) -> None:
    chain = encode_chain(
        [{"phone": "+13125550100", "timeout_seconds": 25, "label": "manager"}]
    )
    r = client.post(
        f"/twilio/dial-owner-fallback?chain={chain}",
        data={"DialCallStatus": "completed"},
    )
    assert r.status_code == 200
    assert "<Hangup" in r.text


def test_escalation_fallback_completed_hangs_up(client: TestClient) -> None:
    r = client.post(
        "/twilio/escalation-fallback",
        data={"DialCallStatus": "completed"},
    )
    assert r.status_code == 200
    assert "<Hangup" in r.text


def test_escalation_fallback_empty_chain_returns_take_message(client: TestClient) -> None:
    r = client.post(
        "/twilio/escalation-fallback",
        data={"DialCallStatus": "no-answer"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "<Say>" in body
    assert '<Stream url="wss://agent.example.com/twilio/stream"' in body


def test_escalation_fallback_with_chain_dials_next(client: TestClient) -> None:
    chain = encode_chain(
        [{"phone": "+13125550200", "timeout_seconds": 20, "label": "kitchen"}]
    )
    r = client.post(
        f"/twilio/escalation-fallback?chain={chain}",
        data={"DialCallStatus": "no-answer"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "<Dial " in body
    assert 'timeout="20"' in body
    assert "+13125550200</Dial>" in body
    # Remaining chain after popping the single entry is empty.
    import re

    m = re.search(r'action="(/twilio/escalation-fallback\?chain=[^"]*)"', body)
    assert m is not None
    next_chain = m.group(1).split("chain=", 1)[1]
    assert decode_chain(next_chain) == []


def test_escalation_fallback_with_two_contact_chain_forwards_tail(client: TestClient) -> None:
    contacts = [
        {"phone": "+13125550200", "timeout_seconds": 20, "label": "kitchen"},
        {"phone": "+13125550300", "timeout_seconds": 25, "label": "owner2"},
    ]
    chain = encode_chain(contacts)
    r = client.post(
        f"/twilio/escalation-fallback?chain={chain}",
        data={"DialCallStatus": "busy"},
        headers={"Host": "agent.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "+13125550200</Dial>" in body
    import re

    m = re.search(r'action="(/twilio/escalation-fallback\?chain=[^"]*)"', body)
    assert m is not None
    next_chain = m.group(1).split("chain=", 1)[1]
    remaining = decode_chain(next_chain)
    assert len(remaining) == 1
    assert remaining[0]["phone"] == "+13125550300"
