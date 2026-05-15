import json
from collections.abc import Callable

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState


def test_appends_event(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory()
    r = c.post(
        "/api/calls/CA1/event",
        headers=auth_headers,
        json={"kind": "transcript_chunk", "payload": {"role": "user", "text": "hello"}},
    )
    assert r.status_code == 202
    line = state.event_log.path.read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["call_sid"] == "CA1"
    assert rec["kind"] == "transcript_chunk"


def test_appends_event_to_firestore_call_store(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    r = c.post(
        "/api/calls/CA1/event",
        headers=auth_headers,
        json={"kind": "toolCalled", "payload": {"name": "lookupHours", "args": {}}},
    )
    assert r.status_code == 202
    assert r.json() == {"ok": True}

    assert state.call_store is not None
    events = list(state.call_store.iter_events("CA1"))
    assert len(events) == 1
    assert events[0].kind == "toolCalled"
    assert events[0].payload == {"name": "lookupHours", "args": {}}

    # Parent /calls/CA1 was upserted with placeholder phones since none supplied.
    call = state.call_store.get_call("CA1")
    assert call is not None
    assert call.caller_phone == "+0"
    assert call.from_number == "+0"
