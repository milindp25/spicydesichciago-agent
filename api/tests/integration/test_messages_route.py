import json
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_messages_records_event_and_sends_sms_to_owner(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory()
    r = c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "callback_number": "+13125551111", "reason": "catering"},
    )
    assert r.status_code == 202
    assert r.json()["sms_sent"] is True

    # Owner SMS + caller confirmation (tenant has sms_confirmation_to_caller=True).
    assert len(state.twilio.sms_calls) == 2
    owner_msg = state.twilio.sms_calls[0]
    assert owner_msg["to"] == "+15555550199"
    assert "catering" in owner_msg["body"]

    caller_msg = state.twilio.sms_calls[1]
    assert caller_msg["to"] == "+13125551111"

    line = state.event_log.path.read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["call_sid"] == "CA1"
    assert rec["kind"] == "message_taken"
    assert rec["payload"]["sms_sent"] is True


def test_messages_requires_callback_number(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "x"},
    )
    assert r.status_code == 400
