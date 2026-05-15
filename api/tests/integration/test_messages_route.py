import re
from collections.abc import Callable

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState


def test_messages_records_event_and_sends_sms_to_owner(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    r = c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "callback_number": "+13125551111", "reason": "catering"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["sms_sent"] is True
    assert isinstance(body["message_id"], str) and body["message_id"]

    # Owner SMS + caller confirmation (tenant has sms_confirmation_to_caller=True).
    assert len(state.twilio.sms_calls) == 2
    owner_msg = state.twilio.sms_calls[0]
    assert owner_msg["to"] == "+15555550199"
    owner_body = owner_msg["body"]
    assert "catering" in owner_body
    assert "+13125551111" in owner_body
    assert "tel:+13125551111" in owner_body
    assert re.search(r"\b\d{1,2}:\d{2}\s*(AM|PM)\b", owner_body), (
        f"no time-of-day marker in {owner_body!r}"
    )

    caller_msg = state.twilio.sms_calls[1]
    assert caller_msg["to"] == "+13125551111"

    # Firestore: primary Message record
    assert state.message_store is not None
    msgs = list(state.message_store.list_unhandled())
    assert len(msgs) == 1
    _id, msg = msgs[0]
    assert msg.call_sid == "CA1"
    assert msg.caller_phone == "+13125551111"
    assert msg.reason == "catering"

    # Firestore: mirrored call event under /calls/CA1/events
    assert state.call_store is not None
    events = list(state.call_store.iter_events("CA1"))
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "messageTaken"
    assert ev.payload["sms_sent"] is True
    assert ev.payload["message_id"] == body["message_id"]

    # Parent /calls/CA1 doc was upserted with the dialed Twilio number
    call = state.call_store.get_call("CA1")
    assert call is not None
    assert call.from_number == "+15555550100"
    assert call.caller_phone == "+13125551111"


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
