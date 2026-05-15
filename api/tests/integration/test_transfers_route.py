from collections.abc import Callable

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState


def test_returns_take_message_outside_hours(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    r = c.post(
        "/api/transfers?now=2026-05-03T09:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "take_message"
    assert body["redirect_ok"] is False
    # No live-call redirect when we decide to take a message instead.
    assert state.twilio.redirects == []

    # Firestore: transferDecided event written under /calls/CA1/events.
    events = list(state.call_store.iter_events("CA1"))
    assert len(events) == 1
    assert events[0].kind == "transferDecided"
    assert events[0].payload["decision"]["action"] == "take_message"
    assert events[0].payload["reason"] == "owner please"


def test_returns_transfer_in_hours(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory(agent_public_url="https://agent.example.com")
    r = c.post(
        "/api/transfers?now=2026-01-05T20:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "transfer"
    assert body["target"] == "+15555550199"
    assert body["redirect_ok"] is True

    assert len(state.twilio.redirects) == 1
    redirect = state.twilio.redirects[0]
    assert redirect["call_sid"] == "CA1"
    assert redirect["twiml_url"] == (
        "https://agent.example.com/twilio/dial-owner?to=+15555550199"
    )


def test_transfer_no_redirect_when_agent_public_url_unset(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory(agent_public_url="")
    r = c.post(
        "/api/transfers?now=2026-01-05T20:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "transfer"
    assert body["redirect_ok"] is False
    assert state.twilio.redirects == []
