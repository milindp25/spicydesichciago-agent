import json
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_messages_records_event(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory()
    r = c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "callback_number": "+1555", "reason": "catering"},
    )
    assert r.status_code == 202
    line = state.event_log.path.read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["call_sid"] == "CA1"
    assert rec["kind"] == "message_taken"


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
