import json
from collections.abc import Callable

from fastapi.testclient import TestClient

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
