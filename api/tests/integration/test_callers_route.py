from collections.abc import Callable
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState
from app.domain.call import CallEvent


def test_caller_history_returning_caller_with_message(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    assert state.caller_store is not None
    assert state.call_store is not None

    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    state.caller_store.upsert_on_call(
        phone="+13125551111",
        ts=now,
        call_sid="CA1",
        outcome="messageTaken",
    )
    state.call_store.append_event(
        call_sid="CA1",
        event=CallEvent(ts=now, kind="messageTaken", payload={"reason": "catering"}),
        caller_phone_for_upsert="+13125551111",
        from_number_for_upsert="+15555550100",
    )

    r = c.get(
        "/api/callers/history?phone=%2B13125551111",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == "+13125551111"
    assert body["is_returning"] is True
    assert body["call_count"] == 1
    assert len(body["events"]) == 1
    ev = body["events"][0]
    assert ev["kind"] == "messageTaken"
    assert ev["call_sid"] == "CA1"
    assert "catering" in ev["summary"]


def test_caller_history_unknown_caller_is_empty(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, _state = client_factory(firestore_db=firestore_db)
    r = c.get(
        "/api/callers/history?phone=%2B19999999999",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == "+19999999999"
    assert body["is_returning"] is False
    assert body["call_count"] == 0
    assert body["events"] == []
